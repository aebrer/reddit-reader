# reddit-reader

Python command-line reader and dreb skill for public Reddit content.

## Structure

- `scripts/reddit_fetch.py` — single mobile GraphQL client, anonymous session lifecycle, URL validation, post conversion, comment tree merging, cursor pagination
- `scripts/read_post.py` — post/comment CLI and threaded plaintext output
- `scripts/read_subreddit.py` — subreddit and aggregate feed CLI
- `scripts/search_subreddit.py` — scoped subreddit search CLI
- `skills/reddit-reader/SKILL.md` — installed skill instructions
- `tests/test_reddit_reader.py` — offline regression tests
- `tests/test_live.py` — opt-in live acceptance tests

## Development

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
REDDIT_READER_LIVE=1 .venv/bin/python -m unittest discover -s tests -v
```

- Python 3.10+, `curl_cffi` pinned in `requirements.txt`; no Node.js or browser requirement.
- GraphQL is the only content backend. Do not reintroduce JSON/cookie/Redlib/browser fallback chains.
- Use the checkout's `.venv/bin/python` in skill commands, without relying on activation.
- Tokens/device identifiers are ephemeral. Do not log tokens, inspect browser profiles, or commit captured live sessions.
- Preserve parent/reply relationships, paragraph breaks, unknown scores, and the linked-comment `<<<` marker. Deleted nodes can omit their IDs; recover identity from focused requests or direct children's parent IDs before merging pages.
- Missing linked comments/ancestors and malformed/error responses must fail explicitly. Never substitute an unrelated thread or silently use partial GraphQL data.
- `--max-pages` bounds all comment requests; warn on omitted relevant continuations. Depth/limit filter only the broader section of a linked-comment request.
- Search must stay inside the requested subreddit. Verify returned subreddit names as well as query syntax.
- Keep offline tests independent of Reddit; run the live suite before declaring a transport change working. `npm test` is retired with the old JavaScript backend.
- API hashes, mobile app headers, and browser TLS fingerprints are external dependencies. Diagnose actual responses before changing them.
