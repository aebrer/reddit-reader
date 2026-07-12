#!/usr/bin/env python3
"""Fetch a Reddit post and its comments in a clean, readable format.

Supports:
- Direct post URLs: reddit.com/r/sub/comments/id/title/
- Share links: reddit.com/r/sub/s/shortcode
- Comment permalinks: reddit.com/r/sub/comments/id/title/commentid/
"""

import argparse
import re
from urllib.parse import urlparse

from reddit_fetch import fetch_json, resolve_redirect_url


def resolve_url(url: str) -> str:
    """Resolve share links and normalize to old.reddit.com."""
    # Resolve /s/ share links via redirect.
    if "/s/" in url:
        url = resolve_redirect_url(url)

    # Normalize to old.reddit.com
    parsed = urlparse(url)
    url = url.replace(parsed.netloc, "old.reddit.com")

    # Strip query params
    url = url.split("?")[0]

    # Ensure trailing slash
    if not url.endswith("/"):
        url += "/"

    return url


def detect_comment_id(url: str) -> str | None:
    """Extract a linked comment ID from the URL if present."""
    # Pattern: /comments/postid/title/commentid/
    match = re.search(r"/comments/\w+/[^/]*/(\w+)/?$", url)
    return match.group(1) if match else None


def format_post(post_data: dict) -> str:
    """Format the post header."""
    lines = []
    lines.append(f"TITLE: {post_data['title']}")
    lines.append(f"AUTHOR: u/{post_data['author']} | SCORE: {post_data['score']} | COMMENTS: {post_data['num_comments']}")
    lines.append(f"SUBREDDIT: r/{post_data['subreddit']}")

    if post_data.get("selftext"):
        lines.append("")
        lines.append(post_data["selftext"])

    if post_data.get("url_overridden_by_dest"):
        url = post_data["url_overridden_by_dest"]
        if not url.startswith("https://www.reddit.com"):
            lines.append(f"LINK: {url}")

    return "\n".join(lines)


def extract_comments(children: list, max_depth: int, highlight_id: str | None = None,
                     min_depth: int = 0) -> list[str]:
    """Recursively extract comments into formatted lines.

    min_depth: normalize indentation so this depth renders at column 0.
    """
    lines = []
    for child in children:
        if child["kind"] != "t1":
            continue
        d = child["data"]
        depth = d.get("depth", 0)
        if depth > max_depth:
            continue

        display_depth = depth - min_depth
        indent = "  " * display_depth
        marker = " <<<" if highlight_id and d["id"] == highlight_id else ""
        body = d["body"].replace("\n", f"\n{indent}  ")
        lines.append(f"{indent}[{d['score']}] u/{d['author']}: {body}{marker}")

        if isinstance(d.get("replies"), dict):
            lines.extend(extract_comments(
                d["replies"]["data"]["children"],
                max_depth,
                highlight_id,
                min_depth
            ))
    return lines


def post_url_from_comment_url(url: str) -> str:
    """Strip comment ID from a permalink to get the base post URL."""
    parts = url.rsplit("/comments/", 1)
    segments = parts[1].split("/")
    # /comments/postid/title/ — take first two segments
    return parts[0] + "/comments/" + segments[0] + "/" + segments[1] + "/"


def main():
    parser = argparse.ArgumentParser(description="Read a Reddit post and its comments.")
    parser.add_argument("url", help="Reddit post URL (direct, share link, or comment permalink)")
    parser.add_argument("--depth", type=int, default=4, help="Max comment nesting depth (default: 4)")
    parser.add_argument("--limit", type=int, default=30, help="Max top-level comments to show (default: 30)")
    args = parser.parse_args()

    url = resolve_url(args.url)
    highlight_id = detect_comment_id(url)

    if highlight_id:
        # Fetch the comment permalink with context to get the full parent chain
        context_data = fetch_json(url, extra_params="context=10")

        post = context_data[0]["data"]["children"][0]["data"]
        print(format_post(post))
        print("---")

        # Show the linked thread (parents → linked comment → replies) with no depth limit
        context_comments = context_data[1]["data"]["children"]
        root_depth = 0
        if context_comments and context_comments[0]["kind"] == "t1":
            root_depth = context_comments[0]["data"].get("depth", 0)
        context_lines = extract_comments(
            context_comments, max_depth=999, highlight_id=highlight_id,
            min_depth=root_depth
        )
        print(f"=== LINKED THREAD (comment {highlight_id}) ===")
        print("\n".join(context_lines))

        # Now fetch the broader thread
        post_url = post_url_from_comment_url(url)
        data = fetch_json(post_url)
        comments = data[1]["data"]["children"]
        if args.limit:
            comments = comments[:args.limit]
        lines = extract_comments(comments, args.depth)

        print(f"\n=== FULL THREAD (top {args.limit}, depth {args.depth}) ===")
        print("\n".join(lines))

        total = post["num_comments"]
        shown = len([l for l in lines if l.strip().startswith("[")])
        if shown < total:
            print(f"\n--- Showing {shown} of {total} comments (depth={args.depth}, limit={args.limit}) ---")
    else:
        data = fetch_json(url)

        post = data[0]["data"]["children"][0]["data"]
        print(format_post(post))
        print("---")

        comments = data[1]["data"]["children"]
        if args.limit:
            comments = comments[:args.limit]

        lines = extract_comments(comments, args.depth)
        print("\n".join(lines))

        total = post["num_comments"]
        shown = len([l for l in lines if l.strip().startswith("[")])
        if shown < total:
            print(f"\n--- Showing {shown} of {total} comments (depth={args.depth}, limit={args.limit}) ---")


if __name__ == "__main__":
    main()
