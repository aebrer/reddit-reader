#!/usr/bin/env python3
"""Read subreddit listings using Reddit's mobile GraphQL API."""

import argparse

from reddit_fetch import RedditClient, RedditError, normalize_subreddit, positive_int


def format_post(post: dict, index: int) -> str:
    flair = f" [{post['link_flair_text']}]" if post.get("link_flair_text") else ""
    score = post['score'] if post.get('score') is not None else '?'
    lines = [f"{index}. [{score}] {post['title']}{flair}",
             f"   u/{post['author']} | {post['num_comments']} comments",
             f"   https://reddit.com{post['permalink']}"]
    if post.get("selftext"):
        preview = post["selftext"][:150].replace("\n", " ")
        if len(post["selftext"]) > 150:
            preview += "..."
        lines.append(f"   > {preview}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Read recent posts from a subreddit.")
    parser.add_argument("subreddit", help="Subreddit name, r/name, or full URL")
    parser.add_argument("--sort", choices=["hot", "new", "top", "rising"], default="hot")
    parser.add_argument("--limit", type=positive_int, default=15, help="Posts to show (default: 15)")
    args = parser.parse_args()
    try:
        subreddit = normalize_subreddit(args.subreddit)
        with RedditClient() as client:
            posts = client.subreddit(subreddit, args.sort, args.limit)
    except RedditError as error:
        parser.exit(1, f"Unable to retrieve Reddit content: {error}\n")
    print(f"r/{subreddit} — {args.sort}")
    print("=" * 60)
    for index, post in enumerate(posts, 1):
        print(format_post(post, index))
        print()


if __name__ == "__main__":
    main()
