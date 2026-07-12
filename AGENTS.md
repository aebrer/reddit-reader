# reddit-reader

Lightweight scripts for reading Reddit content from the command line. Used as a skill for fetching Reddit posts and subreddit listings when URLs come up in conversation.

## Structure

- `scripts/read_post.py` — fetch a single post + threaded comments
- `scripts/read_subreddit.py` — fetch subreddit listing
- `skills/reddit-reader/` — dreb skill

## Key details

- No dependencies beyond Python 3 stdlib + curl
- Fetches via Reddit's undocumented `.json` endpoint on old.reddit.com
- If unauthenticated curl is blocked, retries with local Firefox Reddit cookies, then a configurable Redlib instance
- `search_subreddit.py` is the preferred path for recent Reddit research because web indexes lag
- Rate limit: ~80 direct Reddit requests before 429 errors; public Redlib availability can vary
