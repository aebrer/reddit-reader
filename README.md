# reddit-reader

Lightweight command-line scripts for reading Reddit posts, comment threads, and subreddit listings — no API keys or OAuth. The basic paths need only Python 3 and `curl`; an optional Playwright/Chromium fallback handles blocked post and comment pages.

Tries Reddit's undocumented `.json` endpoints on old.reddit.com, local Firefox cookies, then Redlib. If those fail for a post/comment URL, it renders public Reddit HTML in Chromium. Output is clean, formatted plaintext designed to be easy to read in a terminal or pipe into an LLM.

> **Note:** Reddit sometimes blocks unauthenticated command-line requests at the network-security layer. The scripts retry with Reddit cookies from the local Firefox profile and then fall back to a public Redlib frontend. Only Reddit cookies are exported to a temporary jar, which is deleted on exit. Set `REDDIT_READER_FIREFOX_COOKIES=0` to disable cookies, `REDDIT_READER_FIREFOX_PROFILE=/path/to/profile-or-cookies.sqlite` to choose a profile, or `REDDIT_READER_REDLIB_INSTANCE=https://example.com` to select another Redlib instance.

## Optional browser fallback

```bash
npm ci
npx playwright install chromium
```

Requires Node.js 18+ and Chromium's system libraries. The browser fallback uses an isolated, logged-out browser; it does not reuse your Firefox login or persist browser state. It preserves reply relationships using comment IDs and parent IDs, paragraph breaks, and the `<<<` marker on a linked comment. A response missing the requested comment is an error, not a successful fetch of an unrelated thread.

All fallbacks are announced on stderr. Browser output includes only rendered comments: unexpanded replies may be omitted, and `--depth`/`--limit` filter the retrieved comments rather than guaranteeing that many are fetched. Hidden or unavailable browser scores appear as `?`. Reddit can still block a browser request; failures exit nonzero with diagnostics.

## Usage

### Read a post and its comments

```bash
python3 scripts/read_post.py "https://reddit.com/r/..." [--depth N] [--limit N]
```

- `--depth` — max comment nesting depth (default: 4)
- `--limit` — max top-level comments (default: 30)
- Supports direct links, `/s/` share links, and comment permalinks
- Comment permalinks show available ancestors and replies, with the linked comment marked `<<<` and reply nesting preserved

### Browse a subreddit

```bash
python3 scripts/read_subreddit.py "SUBREDDIT" [--sort MODE] [--limit N]
```

- Accepts bare names (`unixporn`), shorthand (`r/unixporn`), or full URLs
- `--sort` — `hot` (default), `new`, `top`, `rising`
- `--limit` — number of posts (default: 15)

### Search a subreddit

```bash
python3 scripts/search_subreddit.py "SUBREDDIT" "SEARCH TERMS" [--sort MODE] [--time RANGE] [--limit N]
```

- Searches only the selected subreddit
- `--sort` — `new` (default), `relevance`, `hot`, `top`, or `comments`
- `--time` — `year` (default), `hour`, `day`, `week`, `month`, or `all`
- Useful for current research that general-purpose search engines may not have indexed

## Why?

Reddit's web UI is heavy and hostile to readability. These scripts give you the content — post text, scores, threaded comments — without the bloat. They're also handy when you hit Reddit links from an environment where the site doesn't render well (terminal-only machines, SSH sessions, inside an AI coding agent, etc.).

## Use with dreb

This project is primarily designed as a skill for [**dreb**](https://github.com/aebrer/dreb), an open-source AI coding agent harness. The `skills/` directory contains a dreb skill definition that lets the agent automatically read Reddit links that come up in conversation — no manual invocation needed.

If you're using dreb, symlink or copy `skills/reddit-reader/` into your `~/.dreb/agent/skills/` directory and update the script paths in `SKILL.md`. The agent will then handle Reddit URLs for you.

Works great standalone too, of course.

## Tests

```bash
npm test
```

Runs offline Python and JavaScript regression tests, including parent-ID threading, linked-comment validation, fallback ordering, and browser readiness during redirects. No Reddit requests are made by the test suite.

## License

[MIT](LICENSE)
