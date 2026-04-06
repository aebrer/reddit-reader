# reddit-reader

Lightweight command-line scripts for reading Reddit posts, comment threads, and subreddit listings — no API keys, no OAuth, no dependencies beyond Python 3 and `curl`.

Works by hitting Reddit's undocumented `.json` endpoints on old.reddit.com. Output is clean, formatted plaintext designed to be easy to read in a terminal or pipe into an LLM.

> **Note:** This only works from residential IPs. Reddit blocks requests from cloud/VPS providers.

## Usage

### Read a post and its comments

```bash
python3 scripts/read_post.py "https://reddit.com/r/..." [--depth N] [--limit N]
```

- `--depth` — max comment nesting depth (default: 4)
- `--limit` — max top-level comments (default: 30)
- Supports direct links, `/s/` share links, and comment permalinks
- Comment permalinks show the full parent chain to root, with the linked comment marked `<<<`

### Browse a subreddit

```bash
python3 scripts/read_subreddit.py "SUBREDDIT" [--sort MODE] [--limit N]
```

- Accepts bare names (`unixporn`), shorthand (`r/unixporn`), or full URLs
- `--sort` — `hot` (default), `new`, `top`, `rising`
- `--limit` — number of posts (default: 15)

## Why?

Reddit's web UI is heavy and hostile to readability. These scripts give you the content — post text, scores, threaded comments — without the bloat. They're also handy when you hit Reddit links from an environment where the site doesn't render well (terminal-only machines, SSH sessions, inside an AI coding agent, etc.).

## Use with dreb

This project is primarily designed as a skill for [**dreb**](https://github.com/aebrer/dreb), an open-source AI coding agent harness. The `skills/` directory contains a dreb skill definition that lets the agent automatically read Reddit links that come up in conversation — no manual invocation needed.

If you're using dreb, symlink or copy `skills/reddit-reader/` into your `~/.dreb/agent/skills/` directory and update the script paths in `SKILL.md`. The agent will then handle Reddit URLs for you.

Works great standalone too, of course.

## License

[MIT](LICENSE)
