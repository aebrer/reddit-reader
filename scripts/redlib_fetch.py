"""Redlib HTML fallback for Reddit requests blocked at the network layer.

Redlib is only used after Reddit JSON and Firefox-cookie retries fail. The parser
converts the small subset of Redlib HTML used by this project into Reddit-like
JSON so the existing formatters can remain unchanged.
"""

from __future__ import annotations

from html.parser import HTMLParser
import os
import re
import subprocess
from typing import Iterator
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


DEFAULT_INSTANCE = "https://safereddit.com"


class Node:
    def __init__(self, tag: str = "", attrs: dict[str, str] | None = None, parent: "Node | None" = None):
        self.tag = tag
        self.attrs = attrs or {}
        self.parent = parent
        self.children: list[Node | str] = []

    @property
    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def text(self) -> str:
        parts: list[str] = []

        def collect(node: Node) -> None:
            for child in node.children:
                if isinstance(child, str):
                    parts.append(child)
                else:
                    collect(child)

        collect(self)
        return " ".join(" ".join(parts).split())

    def descendants(self, class_name: str | None = None, tag: str | None = None) -> Iterator["Node"]:
        for child in self.children:
            if not isinstance(child, Node):
                continue
            if (class_name is None or class_name in child.classes) and (tag is None or tag == child.tag):
                yield child
            yield from child.descendants(class_name, tag)

    def first(self, class_name: str | None = None, tag: str | None = None) -> "Node | None":
        return next(self.descendants(class_name, tag), None)

    def direct(self, class_name: str) -> "Node | None":
        for child in self.children:
            if isinstance(child, Node) and class_name in child.classes:
                return child
        return None


class TreeParser(HTMLParser):
    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("document")
        self.current = self.root

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag, {key: value or "" for key, value in attrs}, self.current)
        self.current.children.append(node)
        if tag not in self.VOID_TAGS:
            self.current = node

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID_TAGS:
            self.current = self.current.parent or self.root

    def handle_endtag(self, tag: str) -> None:
        node = self.current
        while node is not self.root:
            if node.tag == tag:
                self.current = node.parent or self.root
                return
            node = node.parent or self.root

    def handle_data(self, data: str) -> None:
        self.current.children.append(data)


def _instance() -> str:
    return os.environ.get("REDDIT_READER_REDLIB_INSTANCE", DEFAULT_INSTANCE).rstrip("/")


def _redlib_url(reddit_url: str) -> str:
    parsed = urlparse(reddit_url)
    path = parsed.path
    if path.endswith("/.json"):
        path = path[:-6] + "/"
    elif path.endswith(".json"):
        path = path[:-5]
    instance = urlparse(_instance())
    return urlunparse((instance.scheme, instance.netloc, path, "", parsed.query, ""))


def _fetch_tree(reddit_url: str) -> Node:
    url = _redlib_url(reddit_url)
    result = subprocess.run(
        ["curl", "-sS", "-L", "--fail", "--max-time", "30", url],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Redlib fallback failed for {url}: {result.stderr.strip()}")
    parser = TreeParser()
    parser.feed(result.stdout)
    return parser.root


def _number(text: str) -> int:
    match = re.search(r"-?[\d,]+", text)
    return int(match.group(0).replace(",", "")) if match else 0


def _author(header: str) -> str:
    match = re.search(r"u/([^\s•]+)", header)
    return match.group(1) if match else "[unknown]"


def _subreddit(header: str) -> str:
    match = re.search(r"r/([^\s•]+)", header)
    return match.group(1) if match else "[unknown]"


def _post_href(post: Node) -> str:
    title = post.first("post_title")
    if title:
        for link in title.descendants(tag="a"):
            href = link.attrs.get("href", "")
            if "/comments/" in href:
                return href
    for link in post.descendants(tag="a"):
        href = link.attrs.get("href", "")
        if "/comments/" in href:
            return href
    return ""


def _post_data(post: Node) -> dict:
    title_node = post.first("post_title")
    header_node = post.first("post_header")
    score_node = post.first("post_score")
    body_node = post.first("post_body")
    header = header_node.text() if header_node else ""
    href = _post_href(post)
    comments_match = re.search(r"(\d+) comments?", post.text())
    flair_node = post.first("post_flair")
    return {
        "title": title_node.text() if title_node else "[untitled]",
        "author": _author(header),
        "score": _number(score_node.text()) if score_node else 0,
        "num_comments": int(comments_match.group(1)) if comments_match else 0,
        "subreddit": _subreddit(header),
        "selftext": body_node.text() if body_node else "",
        "permalink": href,
        "link_flair_text": flair_node.text() if flair_node else None,
        "stickied": "stickied" in post.classes,
    }


def _direct_child_comments(node: Node) -> list[Node]:
    comments: list[Node] = []
    for child in node.children:
        if not isinstance(child, Node):
            continue
        if "comment" in child.classes:
            comments.append(child)
        elif "replies" in child.classes or "thread" in child.classes:
            comments.extend(_direct_child_comments(child))
    return comments


def _comment_data(comment: Node, depth: int) -> dict:
    body = comment.direct("comment_body") or comment.first("comment_body")
    author = comment.direct("comment_author") or comment.first("comment_author")
    score = comment.first("comment_score")
    replies_node = comment.first("replies")
    replies = [_comment_child(child, depth + 1) for child in _direct_child_comments(replies_node)] if replies_node else []
    permalink = ""
    for link in comment.descendants(tag="a"):
        href = link.attrs.get("href", "")
        if "/comments/" in href and "context=" in href:
            permalink = href
            break
    comment_id = ""
    match = re.search(r"/comments/[\w]+/[^/]+/([\w]+)/", permalink)
    if match:
        comment_id = match.group(1)
    return {
        "id": comment_id,
        "author": (author.text().removeprefix("u/") if author else "[unknown]"),
        "score": _number(score.text()) if score else 0,
        "body": body.text() if body else "[unavailable]",
        "depth": depth,
        "replies": {"data": {"children": replies}} if replies else "",
    }


def _comment_child(comment: Node, depth: int) -> dict:
    return {"kind": "t1", "data": _comment_data(comment, depth)}


def fetch_compatible(reddit_url: str) -> dict | list:
    """Fetch Redlib and return the Reddit JSON subset consumed by the scripts."""
    tree = _fetch_tree(reddit_url)
    parsed = urlparse(reddit_url)

    if "/comments/" in parsed.path:
        post = tree.first("post")
        if not post:
            raise RuntimeError("Redlib returned no post")
        threads = list(tree.descendants("thread"))
        top_comments: list[Node] = []
        for thread in threads:
            top_comments.extend(_direct_child_comments(thread))
        # Keep only comments whose nearest comment ancestor is absent.
        top_comments = [c for c in top_comments if not any("comment" in a.classes for a in _ancestors(c))]
        post_data = _post_data(post)
        if not post_data["num_comments"]:
            post_data["num_comments"] = len(list(tree.descendants("comment")))
        return [
            {"data": {"children": [{"kind": "t3", "data": post_data}]}},
            {"data": {"children": [_comment_child(c, 0) for c in top_comments]}},
        ]

    posts = [_post_data(post) for post in tree.descendants("post")]
    return {"data": {"children": [{"kind": "t3", "data": post} for post in posts]}}


def _ancestors(node: Node) -> Iterator[Node]:
    current = node.parent
    while current:
        yield current
        current = current.parent


def with_query(url: str, params: dict[str, str | int]) -> str:
    """Return URL with query parameters merged, useful for search endpoints."""
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query))
    query.update({key: str(value) for key, value in params.items()})
    return urlunparse(parsed._replace(query=urlencode(query)))
