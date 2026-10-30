---
name: reddit-reader
description: >
  Read Reddit posts, comments, and subreddit listings. Web Search does not surface up to date reddit results, use this!
---

# Reddit Reader

Uses Reddit's mobile GraphQL API directly through one TLS-compatible client. No Redlib instance, browser, or browser cookies.

## Read a post and its comments

```bash
~/projects/reddit-reader/.venv/bin/python ~/projects/reddit-reader/scripts/read_post.py "URL" [--depth N] [--limit N] [--max-pages N]
```

- **URL**: Reddit post link, `redd.it` short link, `/s/` share link, or comment permalink
- **--depth**: Max displayed comment nesting depth, starting at zero (default: 4)
- **--limit**: Max top-level comments (default: 30; 0 means all retrieved roots)
- **--max-pages**: Max comment API requests, including focused comment/ancestor requests (default: 20). Increase when stderr reports omitted replies or an ancestry budget limit.
- Comment permalinks show ancestors (root → linked comment `<<<` → retrieved replies) first, then the broader thread. Indentation preserves who replies to whom. Depth/limit flags only affect the broader section.
- Deep replies are retrieved through GraphQL cursors; the client asks for up to 200 comments at 10 levels per request. A large thread can require multiple requests.

## Browse a subreddit

```bash
~/projects/reddit-reader/.venv/bin/python ~/projects/reddit-reader/scripts/read_subreddit.py "SUBREDDIT" [--sort MODE] [--limit N]
```

- **SUBREDDIT**: Name (`unihertz`), shorthand (`r/unihertz`), or full URL; `all` and `popular` also work
- **--sort**: `hot` (default), `new`, `top`, `rising`
- **--limit**: Positive number of non-stickied posts (default: 15); paginates as needed

## Search a subreddit

```bash
~/projects/reddit-reader/.venv/bin/python ~/projects/reddit-reader/scripts/search_subreddit.py "SUBREDDIT" "QUERY" [--sort MODE] [--time RANGE] [--limit N]
```

- **SUBREDDIT**: Name, shorthand, or subreddit URL
- **QUERY**: Reddit search terms, restricted to this subreddit
- **--sort**: `new` (default), `relevance`, `hot`, `top`, or `comments`
- **--time**: `year` (default), `hour`, `day`, `week`, `month`, or `all`
- **--limit**: Positive number of results (default: 25); paginates as needed
- Use this instead of general web search for current Reddit opinions. Search broadly first, then open relevant threads with `read_post.py` rather than relying on titles.

## When to use

- User pastes a Reddit link → use `read_post.py`
- User asks "what's on r/whatever" → use `read_subreddit.py`
- User asks what Reddit users currently think or prefer → use `search_subreddit.py`, then read several result threads
- WebFetch fails on reddit.com → use these scripts
- Your own web search turns up a relevant Reddit thread → use `read_post.py`

## Notes

- Always use the checkout's `.venv/bin/python` as shown; no shell activation is necessary.
- If missing, set up the environment in `~/projects/reddit-reader`: `python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt`.
- There is one fetching method, with anonymous sessions in memory. Old Redlib/Firefox settings no longer apply. HTTP blocks, rate limits, API errors, and missing linked comments fail nonzero; do not try the retired methods.
- If retrieval fails, report the failure. Do not substitute web searches for an unread comment or infer what it said.
- Check stderr for a page-budget warning before claiming that all replies were retrieved.
- Output is already formatted for readability; do not summarize unless asked. Hidden scores are `?`; deleted/removed text is not recoverable.
- For opinion research, distinguish firsthand use reports from generic recommendations and separate conclusions by use case.
- For long threads, increase `--depth`, `--limit`, and/or `--max-pages` as needed.
- Share links follow only Reddit redirects; if Reddit blocks resolution, request a direct permalink.
- The API is undocumented and may change. Do not claim permanent anonymous access.
