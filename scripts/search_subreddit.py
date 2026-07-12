#!/usr/bin/env python3
"""Search posts within a subreddit using Reddit JSON or the Redlib fallback."""

import argparse
from urllib.parse import urlencode

from read_subreddit import format_post, normalize_subreddit
from reddit_fetch import fetch_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Search posts within a subreddit.")
    parser.add_argument("subreddit", help="Subreddit name, r/name, or full URL")
    parser.add_argument("query", help="Search terms")
    parser.add_argument(
        "--sort",
        choices=["relevance", "hot", "top", "new", "comments"],
        default="new",
        help="Result order (default: new)",
    )
    parser.add_argument(
        "--time",
        choices=["hour", "day", "week", "month", "year", "all"],
        default="year",
        help="Time range (default: year)",
    )
    parser.add_argument("--limit", type=int, default=25, help="Number of results (default: 25)")
    args = parser.parse_args()

    subreddit = normalize_subreddit(args.subreddit)
    params = urlencode(
        {
            "q": args.query,
            "restrict_sr": "on",
            "sort": args.sort,
            "t": args.time,
            "limit": args.limit,
        }
    )
    data = fetch_json(f"https://old.reddit.com/r/{subreddit}/search/", params)

    print(f'r/{subreddit} — search: "{args.query}" ({args.sort}, {args.time})')
    print("=" * 60)
    posts = data["data"]["children"][: args.limit]
    for index, child in enumerate(posts, 1):
        print(format_post(child["data"], index))
        print()


if __name__ == "__main__":
    main()
