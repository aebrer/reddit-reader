---
name: reddit-reader
description: >
  Read Reddit posts, comments, and subreddit listings. Web Search does not surface up to date reddit results, use this!
---

# Reddit Reader

## Read a post and its comments

```bash
python3 ~/projects/reddit-reader/scripts/read_post.py "URL" [--depth N] [--limit N]
```

- **URL**: Any Reddit post link — direct, `/s/` share link, or comment permalink
- **--depth**: Max comment nesting depth (default: 4)
- **--limit**: Max top-level comments (default: 30)
- Comment permalinks show available ancestors (root → linked comment `<<<` → replies) first, then the broader thread below. Indentation preserves who replies to whom. Depth/limit flags only affect the broader thread section.

## Browse a subreddit

```bash
python3 ~/projects/reddit-reader/scripts/read_subreddit.py "SUBREDDIT" [--sort MODE] [--limit N]
```

- **SUBREDDIT**: Name (`unihertz`), shorthand (`r/unihertz`), or full URL
- **--sort**: `hot` (default), `new`, `top`, `rising`
- **--limit**: Number of posts (default: 15)

## Search a subreddit

```bash
python3 ~/projects/reddit-reader/scripts/search_subreddit.py "SUBREDDIT" "QUERY" [--sort MODE] [--time RANGE] [--limit N]
```

- **SUBREDDIT**: Name, shorthand, or subreddit URL
- **QUERY**: Reddit search terms
- **--sort**: `new` (default), `relevance`, `hot`, `top`, or `comments`
- **--time**: `year` (default), `hour`, `day`, `week`, `month`, or `all`
- Use this instead of a general web search when researching current Reddit opinions; search-engine indexes lag or omit recent threads
- Search broadly first, then open the most relevant threads with `read_post.py` to inspect comments rather than relying on titles

## When to use

- User pastes a Reddit link → use `read_post.py`
- User asks "what's on r/whatever" → use `read_subreddit.py`
- User asks what Reddit users currently think or prefer → search relevant subreddits with `search_subreddit.py`, then read several result threads
- WebFetch fails on reddit.com → use these scripts; they automatically try Reddit JSON, Firefox cookies, Redlib, then Chromium for post/comment pages
- Your own web search turns up a Reddit thread worth reading → use `read_post.py`

## Notes

- Direct Reddit requests may be blocked even from a residential IP; the scripts automatically fall back to a configurable Redlib instance
- Set `REDDIT_READER_REDLIB_INSTANCE` if the default public instance is unavailable
- For the optional browser fallback, run `npm ci && npx playwright install chromium` in `~/projects/reddit-reader`
- Browser fallback uses public, logged-out HTML and announces itself on stderr. Unexpanded replies may be omitted; hidden/unavailable scores appear as `?`
- If retrieval fails, report that failure. Do not substitute web searches for the unread comment or infer what it said
- Output is already formatted for readability; do not reformat or summarize unless asked
- For opinion research, distinguish firsthand hardware/use reports from generic recommendations and separate conclusions by use case
- For long threads, start with defaults and increase `--depth` or `--limit` if needed
- Share links (`/s/` URLs) are resolved automatically via curl redirect
