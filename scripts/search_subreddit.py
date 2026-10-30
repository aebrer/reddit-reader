#!/usr/bin/env python3
"""Search a subreddit using Reddit's mobile GraphQL API."""

import argparse

from read_subreddit import format_post
from reddit_fetch import RedditClient, RedditError, normalize_subreddit, positive_int


def main() -> None:
    parser = argparse.ArgumentParser(description="Search posts within a subreddit.")
    parser.add_argument("subreddit", help="Subreddit name, r/name, or full URL")
    parser.add_argument("query", help="Search terms")
    parser.add_argument("--sort", choices=["relevance", "hot", "top", "new", "comments"], default="new")
    parser.add_argument("--time", choices=["hour", "day", "week", "month", "year", "all"], default="year")
    parser.add_argument("--limit", type=positive_int, default=25, help="Results to show (default: 25)")
    args = parser.parse_args()
    try:
        subreddit = normalize_subreddit(args.subreddit)
        with RedditClient() as client:
            posts = client.search(subreddit, args.query, args.sort, args.time, args.limit)
    except RedditError as error:
        parser.exit(1, f"Unable to retrieve Reddit content: {error}\n")
    print(f'r/{subreddit} — search: "{args.query}" ({args.sort}, {args.time})')
    print("=" * 60)
    for index, post in enumerate(posts, 1):
        print(format_post(post, index))
        print()


if __name__ == "__main__":
    main()
