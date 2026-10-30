"""Read-only Reddit mobile GraphQL client. No alternate fetching backends."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import re
import sys
import time
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit
import uuid


GQL_URL = "https://gql-fed.reddit.com/"
AUTH_URL = "https://www.reddit.com/auth/v2/oauth/access-token/loid"
APP_ID = "ohXpoqrZYub1kg"
APP_USER_AGENT = "Reddit/Version 2026.42.0/Build 2642021/Android 15"
# Persisted Android operation IDs, verified against live responses on 2026-10-30.
OPERATIONS = {
    "PostComments": "314f29c2494fd78c7844ef2c6b09acb4bef5b37ab50b4ddc01691d6d5c8433f8",
    "PostsByIds": "0e471495bcba33554b6c540b3cf1cae23dd5432a8b741dddc7fd6717dc2520a7",
    "SubredditFeedElements": "97046e2a48050f10a507db354a8da60955ffccb586dcf63163bdfc6610d5cf7a",
    "PopularFeedElements": "728c0f9a4d12c17b8cffe07669bb1a8770b0f2ec0c84e040485f8fad2d9c417f",
    "AllFeedSdui": "0e9c0045dd244e934efd0ea4fefc00cb0b4d91523e2f09c8af075856cb59b937",
    "SearchPosts": "8610e33521c90caa8d12576800c18b708ce0d19df3dfac8e2aad55d9860e4bf9",
}
REDDIT_HOSTS = {"reddit.com", "www.reddit.com", "old.reddit.com", "new.reddit.com",
                "np.reddit.com", "m.reddit.com", "redd.it", "www.redd.it"}
POST_PATH = re.compile(
    r"/(?:r/[^/]+/|user/[^/]+/)?comments/([A-Za-z0-9]+)"
    r"(?:/[^/]*(?:/([A-Za-z0-9]+))?)?/?"
)


class RedditError(RuntimeError):
    """A request failed or Reddit did not return the requested content."""


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise ValueError("must be greater than zero")
    return number


def nonnegative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise ValueError("must not be negative")
    return number


def checked_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme in {"https", "http"} and parsed.hostname in REDDIT_HOSTS
                 and not parsed.username and not parsed.password and parsed.port in {None, 80, 443})
    except ValueError as error:
        raise RedditError("Invalid Reddit URL") from error
    if not valid:
        raise RedditError("Expected a reddit.com or redd.it URL")
    return urlunsplit(("https", parsed.hostname, parsed.path, "", ""))


def normalize_subreddit(value: str) -> str:
    value = value.strip().rstrip("/")
    if "://" in value:
        path = urlsplit(checked_url(value)).path
        match = re.match(r"/r/([A-Za-z0-9_]+)(?:/|$)", path)
        value = match.group(1) if match else ""
    else:
        value = value.removeprefix("r/")
    if not re.fullmatch(r"[A-Za-z0-9_]+", value):
        raise RedditError("Expected a subreddit name, r/name, or Reddit subreddit URL")
    return value


def require_list(value, label: str) -> list:
    if not isinstance(value, list):
        raise RedditError(f"Reddit returned no {label}; the API response may have changed")
    return value


def convert_post(node: dict) -> dict:
    title = node.get("title") or node.get("postTitle")
    if not title or not re.fullmatch(r"t3_[A-Za-z0-9]+", node.get("id", "")):
        raise RedditError("Reddit returned an unavailable or malformed post")
    content = node.get("content") or {}
    outbound = (node.get("outboundLink") or {}).get("url", "")
    # PostsByIds wraps external destinations in a tracking redirect.
    if urlsplit(outbound).hostname == "out.reddit.com":
        outbound = parse_qs(urlsplit(outbound).query).get("url", [""])[0]
    return {
        "id": node["id"][3:], "title": title,
        "author": (node.get("authorInfo") or {}).get("name", "[deleted]"),
        "score": None if node.get("isScoreHidden") else node.get("score"),
        "num_comments": node.get("commentCount", 0),
        "subreddit": (node.get("subreddit") or {}).get("name", ""),
        "selftext": content.get("markdown") or "",
        "permalink": node.get("permalink", ""),
        "url_overridden_by_dest": node.get("url") or outbound,
        "link_flair_text": (node.get("flair") or {}).get("text"),
        "stickied": node.get("isStickied", False),
    }


class CommentTree:
    """Merge comment pages by ID, retaining id-less deleted parents by page depth."""

    def __init__(self, post_id: str):
        self.post_id = "t3_" + post_id
        self.nodes: dict[str, dict] = {}
        self.pending: deque[tuple[str, str]] = deque()
        self.cursors: set[str] = set()
        self.fetched_cursors: set[str] = set()
        self.pages = 0

    def add(self, trees: list, focus: str | None = None) -> None:
        self.pages += 1
        stack: dict[int, str] = {}
        for index, entry in enumerate(trees):
            depth = entry.get("depth")
            if not isinstance(depth, int) or depth < 0:
                raise RedditError("Reddit returned an invalid comment depth")
            stack = {d: key for d, key in stack.items() if d < depth}
            parent = entry.get("parentId") or self.post_id
            # DeletedComment nodes omit their ID; their children's parentId still
            # refers to the unavailable ID, so use the local depth relationship.
            previous_parent = stack.get(depth - 1)
            if previous_parent and previous_parent.startswith("deleted:"):
                parent = previous_parent
            more = entry.get("more")
            if more is not None:
                cursor = more.get("cursor")
                if not isinstance(cursor, str) or not cursor:
                    raise RedditError("Reddit returned a comment continuation without a cursor")
                if cursor in self.fetched_cursors:
                    raise RedditError("Reddit returned a repeated comment cursor")
                if cursor not in self.cursors:
                    self.cursors.add(cursor)
                    self.pending.append((cursor, parent))
                continue
            node = entry.get("node")
            if not isinstance(node, dict):
                raise RedditError("Reddit returned a comment without content")
            deleted = node.get("__typename") == "DeletedComment"
            key = node.get("id")
            if deleted and not key:
                # A focused response identifies its root even when Reddit omits
                # that deleted node's ID. Otherwise its first direct child (or
                # continuation) identifies it through parentId, including across pages.
                key = focus if index == 0 and depth == 0 else None
                for descendant in trees[index + 1:]:
                    if key or descendant["depth"] <= depth:
                        break
                    candidate = descendant.get("parentId")
                    if descendant["depth"] == depth + 1 and isinstance(candidate, str) and re.fullmatch(r"t1_[A-Za-z0-9]+", candidate):
                        key = candidate
                        break
                key = key or f"deleted:{self.pages}:{index}"
            elif not isinstance(key, str) or not re.fullmatch(r"t1_[A-Za-z0-9]+", key):
                raise RedditError("Reddit returned an invalid comment ID")
            if deleted:
                body = "[deleted]"
            elif node.get("isRemoved") or node.get("isAdminTakedown"):
                body = "[removed]"
            else:
                body = (node.get("content") or {}).get("markdown")
                if not isinstance(body, str):
                    raise RedditError(f"Reddit returned comment {key} without its body")
            self.nodes[key] = {
                "id": key.removeprefix("t1_"), "parent_id": parent,
                "author": "[deleted]" if deleted else (node.get("authorInfo") or {}).get("name", "[deleted]"),
                "body": body, "score": None if node.get("isScoreHidden") else node.get("score"),
            }
            stack[depth] = key

    def ancestry(self, key: str) -> list[str]:
        """Return key → root, stopping at a missing parent (which callers can fetch)."""
        chain = []
        while key in self.nodes:
            if key in chain:
                raise RedditError("Reddit returned cyclic comment parents")
            chain.append(key)
            key = self.nodes[key]["parent_id"]
        return chain

    def relevant(self, parent: str, depth: int, limit: int, target: str | None) -> bool:
        roots = [key for key, node in self.nodes.items() if node["parent_id"] == self.post_id]
        if parent == self.post_id:
            return not limit or len(roots) < limit
        chain = self.ancestry(parent)
        if target and target in chain:
            return True
        return bool(chain and chain[-1] in (roots[:limit] if limit else roots)
                    and len(chain) <= depth)

    def render(self, target: str | None = None) -> list[dict]:
        chain = set(self.ancestry(target)) if target else set()
        children: dict[str, list[str]] = {}
        for key, node in self.nodes.items():
            children.setdefault(node["parent_id"], []).append(key)

        def build(key: str, depth: int, below_target: bool = False) -> dict:
            below_target = below_target or key == target
            replies = [build(child, depth + 1, below_target)
                       for child in children.get(key, [])
                       if not target or below_target or child in chain]
            return {"kind": "t1", "data": dict(self.nodes[key], depth=depth,
                    replies={"data": {"children": replies}})}

        # Validate every chain, including disconnected cycles.
        for key in self.nodes:
            ancestors = self.ancestry(key)
            if self.nodes[ancestors[-1]]["parent_id"] != self.post_id:
                raise RedditError(f"Reddit omitted an ancestor of comment {key}")
        return [build(key, 0) for key in children.get(self.post_id, [])
                if not target or key in chain]


@dataclass
class PostResult:
    post: dict
    comments: list[dict]
    linked_comments: list[dict] | None = None
    comment_id: str | None = None


class RedditClient:
    def __init__(self):
        try:
            from curl_cffi import requests
        except ImportError as error:
            raise RedditError("Missing curl_cffi. Install with: .venv/bin/python -m pip install -r requirements.txt") from error
        device = str(uuid.uuid4())
        self.session = requests.Session(impersonate="chrome", headers={
            "User-Agent": APP_USER_AGENT, "Content-Type": "application/json; charset=UTF-8",
            "client-vendor-id": device, "X-Reddit-Device-Id": device,
            "x-reddit-retry": "algo=no-retries", "x-reddit-compression": "1",
            "x-reddit-qos": "50.000", "x-reddit-media-codecs": "available-codecs=video/avc, video/hevc",
        })
        self.token = ""
        self.expires_at = 0.0
        self.session_headers: dict[str, str] = {}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.session.close()

    def _request(self, method: str, url: str, label: str, **kwargs):
        from curl_cffi.requests.exceptions import RequestException
        try:
            response = self.session.request(method, url, timeout=30, allow_redirects=False, **kwargs)
        except RequestException as error:
            # Do not include request objects/headers or anonymous bearer tokens.
            raise RedditError(f"{label}: network request failed ({type(error).__name__})") from error
        if response.status_code >= 400:
            suffix = ""
            if response.status_code == 403:
                suffix = "; Reddit blocked this client"
            elif response.status_code == 429:
                suffix = "; rate limited (retry later)"
            raise RedditError(f"{label}: HTTP {response.status_code}{suffix}")
        return response

    @staticmethod
    def _json(response, label: str) -> dict:
        if response.status_code != 200:
            raise RedditError(f"{label}: unexpected HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as error:
            raise RedditError(f"{label}: Reddit returned non-JSON content") from error
        if not isinstance(data, dict):
            raise RedditError(f"{label}: Reddit returned an invalid JSON response")
        return data

    def _authenticate(self) -> None:
        response = self._request("POST", AUTH_URL, "Anonymous session", auth=(APP_ID, ""),
                                 json={"scopes": ["*", "email", "pii"]})
        data = self._json(response, "Anonymous session")
        token, expires = data.get("access_token"), data.get("expires_in")
        if not isinstance(token, str) or not token or not isinstance(expires, (int, float)) or expires <= 0:
            raise RedditError("Reddit did not issue an anonymous session token")
        self.token = token
        self.expires_at = time.monotonic() + max(1, expires - 60)
        self.session_headers = {name: response.headers[name] for name in
                                ("x-reddit-loid", "x-reddit-session") if name in response.headers}

    def query(self, operation: str, variables: dict) -> dict:
        if time.monotonic() >= self.expires_at:
            self._authenticate()
        response = self._request("POST", GQL_URL, operation,
            headers={**self.session_headers, "Authorization": "Bearer " + self.token},
            json={"operationName": operation, "variables": variables,
                  "extensions": {"persistedQuery": {"version": 1, "sha256Hash": OPERATIONS[operation]}}})
        data = self._json(response, operation)
        if data.get("errors"):
            errors = data["errors"]
            codes = [str((error.get("extensions") or {}).get("code", "UNKNOWN"))
                     for error in errors if isinstance(error, dict)] if isinstance(errors, list) else []
            raise RedditError(f"{operation}: GraphQL error ({', '.join(codes) or 'unknown'}); no partial data used")
        if not isinstance(data.get("data"), dict):
            raise RedditError(f"{operation}: missing GraphQL data")
        return data["data"]

    def post_ids(self, url: str) -> tuple[str, str | None]:
        url = checked_url(url)
        for _ in range(6):
            parsed = urlsplit(url)
            if parsed.hostname in {"redd.it", "www.redd.it"} and re.fullmatch(r"/[A-Za-z0-9]+/?", parsed.path):
                return parsed.path.strip("/"), None
            match = POST_PATH.fullmatch(parsed.path)
            if match:
                return match.group(1), match.group(2)
            if "/s/" not in parsed.path:
                break
            response = self._request("GET", url, "Share link")
            location = response.headers.get("location")
            if response.status_code not in {301, 302, 303, 307, 308} or not location:
                raise RedditError("Reddit did not resolve the share link to a post")
            url = checked_url(urljoin(url, location))
        raise RedditError("Expected a Reddit post/comment permalink or resolvable /s/ share link")

    def _comments(self, post_id: str, sort: str, *, focus: str | None = None,
                  cursor: str | None = None) -> list:
        variables = {"id": "t3_" + post_id, "sortType": sort, "count": 200,
                     "maxDepth": 10, "includeConsistencyToken": False,
                     "includePremiumAvatarTreatment": False}
        if cursor:
            variables["after"] = cursor
        elif focus:
            variables["focusedCommentContext"] = {"commentId": focus, "isFocusedThreadOnly": True}
        data = self.query("PostComments", variables)
        info = data.get("postInfoById") or {}
        if info.get("id") != "t3_" + post_id:
            raise RedditError("Reddit did not return the requested comment thread")
        return require_list((info.get("commentForest") or {}).get("trees"), "comment forest")

    def read_post(self, url: str, depth: int = 4, limit: int = 30, max_pages: int = 20) -> PostResult:
        if depth < 0 or limit < 0 or max_pages < 1:
            raise RedditError("Depth/limit must be nonnegative and max-pages must be positive")
        post_id, comment_id = self.post_ids(url)
        data = self.query("PostsByIds", {"ids": ["t3_" + post_id],
                          "includePostContentPostHint": True, "includePostContentThumbnailEnabled": True})
        posts = require_list(data.get("postsInfoByIds"), "post metadata")
        if len(posts) != 1 or not isinstance(posts[0], dict) or posts[0].get("id") != "t3_" + post_id:
            raise RedditError("Reddit did not return the requested post")
        post = convert_post(posts[0])
        sort = posts[0].get("suggestedCommentSort") or "CONFIDENCE"
        tree = CommentTree(post_id)
        tree.add(self._comments(post_id, sort))
        target = "t1_" + comment_id if comment_id else None
        if target:
            needed = target
            seen = set()
            while needed != tree.post_id:
                if needed in seen:
                    raise RedditError("Reddit returned cyclic linked-comment ancestry")
                seen.add(needed)
                if needed not in tree.nodes:
                    if tree.pages >= max_pages:
                        raise RedditError("Linked-comment ancestry exceeded --max-pages; increase it")
                    tree.add(self._comments(post_id, sort, focus=needed), focus=needed)
                    if needed not in tree.nodes:
                        raise RedditError(f"Reddit did not return linked comment/ancestor {needed}")
                needed = tree.nodes[needed]["parent_id"]

        while tree.pending:
            cursor, parent = tree.pending.popleft()
            if not tree.relevant(parent, depth, limit, target):
                continue
            if tree.pages >= max_pages:
                print("Comment retrieval reached --max-pages; additional replies are omitted. "
                      "Increase --max-pages to retrieve more.", file=sys.stderr)
                break
            tree.fetched_cursors.add(cursor)
            tree.add(self._comments(post_id, sort, cursor=cursor))
        return PostResult(post, tree.render(), tree.render(target) if target else None, comment_id)

    def _listing(self, operation: str, variables: dict, limit: int, *, skip_stickied: bool = False) -> list[dict]:
        if limit < 1:
            raise RedditError("Listing limit must be positive")
        posts, seen_ids, seen_cursors = [], set(), set()
        for _ in range(100):
            data = self.query(operation, dict(variables, pageSize=min(100, limit - len(posts))))
            if operation == "SubredditFeedElements":
                feed = data.get("postFeed") or {}
                if feed.get("__typename") != "Subreddit":
                    raise RedditError("Reddit did not return an accessible subreddit")
                connection = feed.get("elements") or {}
            elif operation == "PopularFeedElements":
                connection = (data.get("popular") or {}).get("elements") or {}
            elif operation == "AllFeedSdui":
                connection = (data.get("allV3") or {}).get("elements") or {}
            else:
                connection = ((data.get("search") or {}).get("general") or {}).get("posts") or {}
            edges = require_list(connection.get("edges"), "listing results")
            if operation == "AllFeedSdui":
                # The all feed provides UI cells, not post bodies. Fetch its organic
                # post IDs through the same GraphQL transport, keeping feed order.
                ids = [edge["node"]["groupId"] for edge in edges
                       if not edge["node"].get("adPayload")
                       and re.fullmatch(r"t3_[A-Za-z0-9]+", edge["node"].get("groupId", ""))]
                metadata = self.query("PostsByIds", {"ids": ids,
                    "includePostContentPostHint": True, "includePostContentThumbnailEnabled": True}) if ids else {"postsInfoByIds": []}
                by_id = {node["id"]: node for node in require_list(metadata.get("postsInfoByIds"), "post metadata")
                         if isinstance(node, dict) and node.get("__typename") == "SubredditPost"}
                nodes = [by_id[key] for key in ids if key in by_id]
            else:
                nodes = [((edge.get("node") or {}).get("postInfo") or {}) if operation == "PopularFeedElements"
                         else (edge.get("node") or {}) for edge in edges]
            for node in nodes:
                if node.get("__typename") != "SubredditPost":
                    continue  # Recommendations and ads are not posts.
                post = convert_post(node)
                if post["id"] not in seen_ids:
                    seen_ids.add(post["id"])
                    if not skip_stickied or not post["stickied"]:
                        posts.append(post)
                if len(posts) == limit:
                    return posts
            page_info = connection.get("pageInfo") or {}
            if page_info.get("hasNextPage") is False:
                return posts
            cursor = page_info.get("endCursor")
            if operation == "AllFeedSdui" and not cursor:
                return posts
            if not isinstance(cursor, str) or not cursor or cursor in seen_cursors:
                raise RedditError("Reddit returned a missing or repeated listing cursor")
            seen_cursors.add(cursor)
            variables = dict(variables, **{"afterCursor" if operation == "SearchPosts" else "after": cursor})
        raise RedditError("Listing exceeded 100 pages before reaching the requested limit")

    def subreddit(self, name: str, sort: str = "hot", limit: int = 15) -> list[dict]:
        if sort not in {"hot", "new", "top", "rising"}:
            raise RedditError("Unsupported subreddit sort")
        name = normalize_subreddit(name)
        operation = {"all": "AllFeedSdui", "popular": "PopularFeedElements"}.get(name.lower(), "SubredditFeedElements")
        variables = {"sort": sort.upper()}
        if operation == "SubredditFeedElements":
            variables.update(subredditName=name, includeSubredditInPosts=True)
        return self._listing(operation, variables, limit, skip_stickied=True)

    def search(self, name: str, query: str, sort: str = "new", time_range: str = "year", limit: int = 25) -> list[dict]:
        if sort not in {"relevance", "hot", "top", "new", "comments"}:
            raise RedditError("Unsupported search sort")
        if time_range not in {"hour", "day", "week", "month", "year", "all"}:
            raise RedditError("Unsupported search time range")
        subreddit = normalize_subreddit(name)
        posts = self._listing("SearchPosts", {"query": f"subreddit:{subreddit} ({query})", "sort": sort.upper(),
            "filters": [{"key": "time_range", "value": time_range}, {"key": "nsfw", "value": "0"}],
            "productSurface": "android"}, limit)
        if any(post["subreddit"].casefold() != subreddit.casefold() for post in posts):
            raise RedditError("Reddit returned search results outside the requested subreddit")
        return posts
