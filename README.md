# reddit-reader

Read Reddit posts, threaded comments, subreddit listings, and subreddit search from the command line. Output is readable plaintext for terminals and coding agents.

All content comes directly from Reddit's mobile GraphQL API through **one transport**, [`curl_cffi`](https://github.com/lexiforest/curl_cffi), with browser-compatible TLS. The client creates an anonymous OAuth session; no Reddit account, API keys, browser login, or external scraping service is required.

## Install

Requires Python 3.10+.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

There is no Node.js or browser dependency. The previous JSON, Firefox-cookie, public Redlib, and Chromium implementations have been removed. Their environment variables no longer apply. The reader does not inspect your browser profile or save session tokens to disk.

## Usage

### Read a post or linked comment

```bash
.venv/bin/python scripts/read_post.py "https://www.reddit.com/r/pebble/comments/1xj4whi/"
.venv/bin/python scripts/read_post.py "REDDIT_COMMENT_URL" --depth 8 --limit 50 --max-pages 30
```

Accepts Reddit post/comment URLs, `redd.it` short links, and `/s/` share links. Share links must resolve through Reddit; blocked or unexpected redirects produce an error.

- `--depth`: maximum displayed comment depth, starting at zero (default: 4).
- `--limit`: maximum top-level comments displayed (default: 30; 0 means all retrieved roots).
- `--max-pages`: maximum comment API requests, including focused comment/ancestor requests (default: 20). Each request asks for up to 200 comments at 10 levels of depth; cursors retrieve further comments and deeper replies.

Comment permalinks show the parent chain, the exact linked comment marked `<<<`, and its retrieved replies first, then the broader thread. Depth/limit only filter the broader section. Reply relationships are reconstructed from comment IDs and parent IDs, including deleted parents whose identity is recoverable from replies. Deleted/removed text stays `[deleted]`/`[removed]`; hidden scores display `?`.

Pagination follows continuations relevant to the requested depth/limit and linked replies. A page-budget limit produces a warning on stderr instead of silently implying that every reply was fetched. If the requested comment or its ancestor chain cannot be retrieved, the command fails rather than printing an unrelated or disconnected thread. Reddit's total count can include deleted or otherwise inaccessible comments.

### Browse a subreddit

```bash
.venv/bin/python scripts/read_subreddit.py pebble --sort new --limit 15
```

Accepts names, `r/name`, or full Reddit subreddit URLs, including the aggregate feeds `all` and `popular`.

- `--sort`: `hot` (default), `new`, `top`, or `rising`.
- `--limit`: positive number of non-stickied posts (default: 15). The client paginates when necessary, up to 100 listing pages.

### Search a subreddit

```bash
.venv/bin/python scripts/search_subreddit.py pebble linux --sort new --time year --limit 25
```

Search is restricted to the specified subreddit; out-of-scope results are rejected.

- `--sort`: `new` (default), `relevance`, `hot`, `top`, or `comments`.
- `--time`: `year` (default), `hour`, `day`, `week`, `month`, or `all`.
- `--limit`: positive number of results (default: 25), with cursor pagination as needed.

Prefer this for current Reddit research: general web search may not have indexed recent posts.

## Errors and maintenance

HTTP failures, rate limits, GraphQL errors (including partial-error responses), malformed responses, and missing linked comments exit nonzero with diagnostics on stderr. There is no alternate backend or silent fallback. Anonymous sessions refresh on expiry; rate-limit errors are reported, not bypassed through token rotation.

This is an **undocumented API**, not a promise of permanent anonymous access. Reddit can change its persisted operations, app authentication, or access policies. Operation hashes, app headers, and TLS configuration live in `scripts/reddit_fetch.py`. Check live behavior before updating them; changing the User-Agent alone does not provide browser-compatible TLS.

Protocol research references: [Redlib's GraphQL migration](https://github.com/polak14/redlib/commit/29f18352cf54be4ffe579f773552acd0c45cdd08) and [`curl_cffi` documentation](https://curl-cffi.readthedocs.io/). This repository implements its own Python client; it does not vendor Redlib's Rust code.

## Use with dreb

Symlink `skills/reddit-reader/` into `~/.dreb/agent/skills/` and adjust the paths in `SKILL.md` if your checkout is not at `~/projects/reddit-reader`. The skill uses the checkout's `.venv/bin/python` explicitly, so it needs no shell activation.

## Tests

Offline regression suite:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Opt-in live verification (makes real Reddit requests):

```bash
REDDIT_READER_LIVE=1 .venv/bin/python -m unittest discover -s tests -v
```

The live suite checks the original deeply linked comment, deleted-parent ancestry, deep continuation, zero-comment posts, aggregate feeds, listing sorts, feed/search pagination beyond 100 results, scoped/empty searches, and missing-target failure. It uses public content that can change or be removed. No live requests run without the environment flag.

## License

[MIT](LICENSE)
