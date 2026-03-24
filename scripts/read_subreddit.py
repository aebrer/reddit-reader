#!/usr/bin/env python3
"""Fetch recent posts from a subreddit in a clean, readable format.

Supports:
- Subreddit URLs: reddit.com/r/subreddit
- Bare subreddit names: unihertz, r/unihertz
- Sort modes: hot (default), new, top, rising
"""

import argparse
import json
import subprocess
import sys


USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"


def normalize_subreddit(input_str: str) -> str:
    """Extract subreddit name from URL or shorthand."""
    input_str = input_str.strip().rstrip("/")

    # Full URL: extract subreddit name
    if "reddit.com" in input_str:
        parts = input_str.split("/r/")
        if len(parts) > 1:
            return parts[1].split("/")[0]

    # r/name format
    if input_str.startswith("r/"):
        return input_str[2:]

    # Bare name
    return input_str


def fetch_json(subreddit: str, sort: str, limit: int) -> dict:
    """Fetch subreddit listing JSON."""
    url = f"https://old.reddit.com/r/{subreddit}/{sort}/.json?limit={limit}"
    result = subprocess.run(
        ["curl", "-s", "-H", f"User-Agent: {USER_AGENT}", "-H", "Accept: application/json", url],
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


def format_post(post: dict, index: int) -> str:
    """Format a single post in the listing."""
    lines = []
    flair = f" [{post['link_flair_text']}]" if post.get("link_flair_text") else ""
    lines.append(f"{index}. [{post['score']}] {post['title']}{flair}")
    lines.append(f"   u/{post['author']} | {post['num_comments']} comments")
    lines.append(f"   https://reddit.com{post['permalink']}")

    if post.get("selftext"):
        preview = post["selftext"][:150].replace("\n", " ")
        if len(post["selftext"]) > 150:
            preview += "..."
        lines.append(f"   > {preview}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Read recent posts from a subreddit.")
    parser.add_argument("subreddit", help="Subreddit name, r/name, or full URL")
    parser.add_argument("--sort", choices=["hot", "new", "top", "rising"], default="hot",
                        help="Sort mode (default: hot)")
    parser.add_argument("--limit", type=int, default=15, help="Number of posts to show (default: 15)")
    args = parser.parse_args()

    subreddit = normalize_subreddit(args.subreddit)
    data = fetch_json(subreddit, args.sort, args.limit)

    print(f"r/{subreddit} — {args.sort}")
    print("=" * 60)

    posts = data["data"]["children"]
    for i, child in enumerate(posts, 1):
        post = child["data"]
        if post.get("stickied"):
            continue
        print(format_post(post, i))
        print()


if __name__ == "__main__":
    main()
