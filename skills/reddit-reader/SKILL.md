---
name: reddit-reader
description: >
  Read Reddit posts, comments, and subreddit listings. Use when: (1) the user sends a Reddit
  URL, (2) your own research points to a Reddit thread (e.g. debugging, hardware discussions),
  (3) the user asks "what's on r/subreddit right now", (4) a WebFetch fails on a reddit.com URL.
  Supports direct links, share links (/s/), and comment permalinks.
---

# Reddit Reader

## Read a post and its comments

```bash
python3 ~/projects/reddit-reader/scripts/read_post.py "URL" [--depth N] [--limit N]
```

- **URL**: Any Reddit post link — direct, `/s/` share link, or comment permalink
- **--depth**: Max comment nesting depth (default: 4)
- **--limit**: Max top-level comments (default: 30)
- Comment permalinks show the full parent chain (root → linked comment `<<<` → replies) first, then the broader thread below. Depth/limit flags only affect the broader thread section.

## Browse a subreddit

```bash
python3 ~/projects/reddit-reader/scripts/read_subreddit.py "SUBREDDIT" [--sort MODE] [--limit N]
```

- **SUBREDDIT**: Name (`unihertz`), shorthand (`r/unihertz`), or full URL
- **--sort**: `hot` (default), `new`, `top`, `rising`
- **--limit**: Number of posts (default: 15)

## When to use

- User pastes a Reddit link → use `read_post.py`
- User asks "what's on r/whatever" → use `read_subreddit.py`
- WebFetch fails on reddit.com → fall back to these scripts
- Your own web search turns up a Reddit thread worth reading → use `read_post.py`

## Notes

- Works from Drew's residential IP — Reddit blocks cloud/VPS IPs
- Output is already formatted for readability; do not reformat or summarize unless asked
- For long threads, start with defaults and increase `--depth` or `--limit` if the user wants more
- Share links (`/s/` URLs) are resolved automatically via curl redirect
