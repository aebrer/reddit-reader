# reddit-reader

Lightweight scripts for reading Reddit content from the command line. Used as a skill for fetching Reddit posts and subreddit listings when URLs come up in conversation.

## Structure

- `scripts/read_post.py` — fetch a single post + threaded comments
- `scripts/read_subreddit.py` — fetch subreddit listing
- `skills/reddit-reader/` — dreb skill

## Key details

- Basic paths use Python 3 stdlib + curl; optional post/comment fallback uses Node.js + Playwright/Chromium (`npm ci`, `npx playwright install chromium`)
- Fetches via Reddit's undocumented `.json` endpoint on old.reddit.com
- If unauthenticated curl is blocked, retries with local Firefox Reddit cookies, then a configurable Redlib instance, then public Reddit HTML in an isolated Chromium browser
- `browser_fetch.py` reconstructs comment trees from IDs/parent IDs; do not flatten replies into plain browser text
- Linked-comment requests must contain the requested ID; browser output may omit unexpanded replies
- Run `npm test` for offline Python and JavaScript regression tests
- `search_subreddit.py` is the preferred path for recent Reddit research because web indexes lag
- Rate limit: ~80 direct Reddit requests before 429 errors; public Redlib availability can vary
