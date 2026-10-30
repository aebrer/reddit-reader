#!/usr/bin/env python3
"""Read a Reddit post or linked comment using the mobile GraphQL API."""

import argparse

from reddit_fetch import RedditClient, RedditError, nonnegative_int, positive_int


def format_post(post_data: dict) -> str:
    lines = [f"TITLE: {post_data['title']}"]
    score = post_data['score'] if post_data.get('score') is not None else '?'
    lines.append(f"AUTHOR: u/{post_data['author']} | SCORE: {score} | COMMENTS: {post_data['num_comments']}")
    lines.append(f"SUBREDDIT: r/{post_data['subreddit']}")
    if post_data.get("selftext"):
        lines.extend(["", post_data["selftext"]])
    if post_data.get("url_overridden_by_dest"):
        url = post_data["url_overridden_by_dest"]
        if not url.startswith("https://www.reddit.com"):
            lines.append(f"LINK: {url}")
    return "\n".join(lines)


def extract_comments(children: list, max_depth: int, highlight_id: str | None = None) -> list[str]:
    lines = []
    for child in children:
        d = child["data"]
        depth = d["depth"]
        if depth > max_depth:
            continue
        indent = "  " * depth
        marker = " <<<" if highlight_id and d["id"] == highlight_id else ""
        body = d["body"].replace("\n", f"\n{indent}  ")
        score = d['score'] if d.get('score') is not None else '?'
        lines.append(f"{indent}[{score}] u/{d['author']}: {body}{marker}")
        lines.extend(extract_comments(d["replies"]["data"]["children"], max_depth, highlight_id))
    return lines


def main():
    parser = argparse.ArgumentParser(description="Read a Reddit post and its comments.")
    parser.add_argument("url", help="Reddit post URL, /s/ share link, or comment permalink")
    parser.add_argument("--depth", type=nonnegative_int, default=4, help="Max comment depth (default: 4)")
    parser.add_argument("--limit", type=nonnegative_int, default=30, help="Top-level comments (default: 30; 0: all)")
    parser.add_argument("--max-pages", type=positive_int, default=20,
                        help="Maximum comment API requests (default: 20; 200 comments per page)")
    args = parser.parse_args()
    try:
        with RedditClient() as client:
            result = client.read_post(args.url, args.depth, args.limit, args.max_pages)
    except RedditError as error:
        parser.exit(1, f"Unable to retrieve Reddit content: {error}\n")

    print(format_post(result.post))
    print("---")
    if result.linked_comments is not None:
        print(f"=== LINKED THREAD (comment {result.comment_id}) ===")
        print("\n".join(extract_comments(result.linked_comments, 999, result.comment_id)))
        print(f"\n=== FULL THREAD (top {args.limit or 'all'}, depth {args.depth}) ===")
    comments = result.comments[:args.limit] if args.limit else result.comments
    lines = extract_comments(comments, args.depth)
    print("\n".join(lines))
    total = result.post["num_comments"]
    if len(lines) < total:
        print(f"\n--- Showing {len(lines)} of {total} comments (depth={args.depth}, limit={args.limit}) ---")


if __name__ == "__main__":
    main()
