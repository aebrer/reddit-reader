# reddit-reader

Lightweight scripts for reading Reddit content from the command line. Used as a Claude Code skill for fetching Reddit posts and subreddit listings when URLs come up in conversation.

## Structure

- `scripts/read_post.py` — fetch a single post + threaded comments
- `scripts/read_subreddit.py` — fetch subreddit listing
- `skills/reddit-reader/` — Claude skill (symlinked to `~/.claude/skills/reddit-reader`)

## Key details

- No dependencies beyond Python 3 stdlib + curl
- Fetches via Reddit's undocumented `.json` endpoint on old.reddit.com
- Only works from residential IPs (Reddit blocks cloud/VPS)
- Rate limit: ~80 requests before 429 errors
