"""Optional Chromium fallback for public post/comment pages.

Uses Playwright only after the dependency-free Reddit/Redlib paths fail. Modern
Reddit HTML is converted to the same threaded JSON subset as the other backends.
"""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
from urllib.parse import urlparse, urlunparse

from redlib_fetch import Node, TreeParser


def _body_text(node: Node | None) -> str:
    """Keep paragraph breaks without including scripts or UI controls."""
    if node is None:
        return "[unavailable]"

    def collect(current: Node) -> str:
        if current.tag in {"script", "style", "template"}:
            return ""
        if current.tag == "br":
            return "\n"
        text = "".join(child if isinstance(child, str) else collect(child)
                       for child in current.children)
        if current.tag in {"p", "div", "blockquote", "pre", "ul", "ol"}:
            return f"\n\n{text}\n\n"
        if current.tag == "li":
            return f"\n- {text}\n"
        return text

    text = re.sub(r"[^\S\n]+", " ", collect(node))
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _own_descendants(node: Node):
    """Walk one comment's content, never a nested reply's content."""
    for child in node.children:
        if not isinstance(child, Node) or child.tag == "shreddit-comment":
            continue
        yield child
        yield from _own_descendants(child)


def _own_slot(node: Node, slot: str) -> Node | None:
    return next((child for child in _own_descendants(node)
                 if child.attrs.get("slot") == slot), None)


def parse_post_html(html: str) -> list:
    parser = TreeParser()
    parser.feed(html)
    post = parser.root.first(tag="shreddit-post")
    if post is None or not post.attrs.get("post-title"):
        raise RuntimeError("Browser returned no Reddit post")
    attrs = post.attrs
    text_body = _own_slot(post, "text-body")
    post_data = {
        "id": attrs.get("id", "").removeprefix("t3_"),
        "title": attrs["post-title"],
        "author": attrs.get("author", "[deleted]"),
        "score": int(attrs["score"]) if attrs.get("score") else None,
        "num_comments": int(attrs.get("comment-count", "0")),
        "subreddit": attrs.get("subreddit-name", "[unknown]"),
        "selftext": _body_text(text_body) if text_body else "",
        "permalink": attrs.get("permalink", ""),
        "url_overridden_by_dest": attrs.get("content-href", ""),
    }

    # Parent IDs, rather than DOM nesting or display order, determine the tree.
    # Modern Reddit can put replies in slots and intermediate wrappers.
    comments: dict[str, dict] = {}
    parents: dict[str, str] = {}
    for node in parser.root.descendants(tag="shreddit-comment"):
        thing_id = node.attrs.get("thingid", "")
        if not thing_id.startswith("t1_") or thing_id in comments:
            continue
        body = _own_slot(node, "comment")
        if body is None:
            raise RuntimeError(f"Browser returned comment {thing_id} without its body")
        action_row = next((child for child in _own_descendants(node)
                           if child.tag == "shreddit-comment-action-row"), None)
        # Reddit sometimes puts a placeholder score=1 on every comment while
        # exposing no vote controls at all. Do not present that as a real score.
        score_hidden = action_row is None or "is-score-hidden" in node.attrs or (
            "is-score-hidden" in action_row.attrs
        )
        comments[thing_id] = {
            "kind": "t1",
            "data": {
                "id": thing_id.removeprefix("t1_"),
                "parent_id": node.attrs.get("parentid", attrs.get("id", "")),
                "author": node.attrs.get("author", "[deleted]"),
                "score": (int(node.attrs["score"])
                          if node.attrs.get("score") and not score_hidden else None),
                "body": _body_text(body),
                "depth": int(node.attrs.get("depth", "0")),
                "replies": {"data": {"children": []}},
            },
        }
        parents[thing_id] = comments[thing_id]["data"]["parent_id"]

    roots = []
    for thing_id, comment in comments.items():
        parent = comments.get(parents[thing_id])
        if parent is None:
            roots.append(comment)
        else:
            parent["data"]["replies"]["data"]["children"].append(comment)

    # Single-comment pages use negative depths for ancestors. Recompute depths
    # from the reconstructed tree so both context and full-thread views agree.
    pending = [(root, 0) for root in roots]
    visited = 0
    while pending:
        comment, depth = pending.pop()
        comment["data"]["depth"] = depth
        visited += 1
        pending.extend((reply, depth + 1)
                       for reply in comment["data"]["replies"]["data"]["children"])
    if visited != len(comments):
        raise RuntimeError("Browser returned cyclic comment parent IDs")
    return [
        {"data": {"children": [{"kind": "t3", "data": post_data}]}},
        {"data": {"children": roots}},
    ]


def fetch_compatible(reddit_url: str) -> list:
    parsed = urlparse(reddit_url)
    path = parsed.path.removesuffix("/.json")
    url = urlunparse(("https", "www.reddit.com", path, "", parsed.query, ""))
    script = Path(__file__).with_suffix(".cjs")
    try:
        result = subprocess.run(
            ["node", str(script), url], capture_output=True, text=True, timeout=90,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"Browser fallback could not run: {error}") from error
    if result.returncode:
        if "Cannot find module 'playwright'" in result.stderr:
            raise RuntimeError(
                "Browser fallback needs Playwright: run npm ci and "
                "npx playwright install chromium in the reddit-reader directory"
            )
        raise RuntimeError(f"Browser fallback failed: {result.stderr.strip()}")
    return parse_post_html(result.stdout)
