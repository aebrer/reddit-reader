#!/usr/bin/env python3
"""Fetch a Reddit post and its comments in a clean, readable format.

Supports:
- Direct post URLs: reddit.com/r/sub/comments/id/title/
- Share links: reddit.com/r/sub/s/shortcode
- Comment permalinks: reddit.com/r/sub/comments/id/title/commentid/
"""

import argparse
import json
import subprocess
import sys
import re
from urllib.parse import urlparse


USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"


def resolve_url(url: str) -> str:
    """Resolve share links and normalize to old.reddit.com."""
    # Resolve /s/ share links via curl redirect
    if "/s/" in url:
        result = subprocess.run(
            ["curl", "-sL", "-o", "/dev/null", "-w", "%{url_effective}", url],
            capture_output=True, text=True
        )
        url = result.stdout.strip()

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


def fetch_json(url: str) -> list:
    """Fetch the .json version of a Reddit URL."""
    json_url = url.rstrip("/") + "/.json"
    result = subprocess.run(
        ["curl", "-s", "-H", f"User-Agent: {USER_AGENT}", "-H", "Accept: application/json", json_url],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"Error fetching URL: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"Failed to parse JSON. Response starts with: {result.stdout[:200]}", file=sys.stderr)
        sys.exit(1)


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


def extract_comments(children: list, max_depth: int, highlight_id: str | None = None) -> list[str]:
    """Recursively extract comments into formatted lines."""
    lines = []
    for child in children:
        if child["kind"] != "t1":
            continue
        d = child["data"]
        depth = d.get("depth", 0)
        if depth > max_depth:
            continue

        indent = "  " * depth
        marker = " <<<" if highlight_id and d["id"] == highlight_id else ""
        body = d["body"].replace("\n", f"\n{indent}  ")
        lines.append(f"{indent}[{d['score']}] u/{d['author']}: {body}{marker}")

        if isinstance(d.get("replies"), dict):
            lines.extend(extract_comments(
                d["replies"]["data"]["children"],
                max_depth,
                highlight_id
            ))
    return lines


def main():
    parser = argparse.ArgumentParser(description="Read a Reddit post and its comments.")
    parser.add_argument("url", help="Reddit post URL (direct, share link, or comment permalink)")
    parser.add_argument("--depth", type=int, default=4, help="Max comment nesting depth (default: 4)")
    parser.add_argument("--limit", type=int, default=30, help="Max top-level comments to show (default: 30)")
    args = parser.parse_args()

    url = resolve_url(args.url)
    highlight_id = detect_comment_id(url)

    # For comment links, strip the comment ID from URL so we get the full thread
    if highlight_id:
        url = re.sub(r"/\w+/?$", "/", url.rsplit("/comments/", 1)[0] + "/comments/" + url.rsplit("/comments/", 1)[1].split("/")[0] + "/" + url.rsplit("/comments/", 1)[1].split("/")[1] + "/")

    data = fetch_json(url)

    # Format post
    post = data[0]["data"]["children"][0]["data"]
    print(format_post(post))
    print("---")

    # Format comments
    comments = data[1]["data"]["children"]
    if args.limit:
        comments = comments[:args.limit]

    lines = extract_comments(comments, args.depth, highlight_id)
    if highlight_id:
        print(f"(Linked comment {highlight_id} marked with <<<)")
    print("\n".join(lines))

    total = post["num_comments"]
    shown = len([l for l in lines if l.strip().startswith("[")])
    if shown < total:
        print(f"\n--- Showing {shown} of {total} comments (depth={args.depth}, limit={args.limit}) ---")


if __name__ == "__main__":
    main()
