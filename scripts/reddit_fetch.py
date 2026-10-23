"""Shared Reddit fetching helpers.

Reddit sometimes blocks unauthenticated curl requests at the network-security layer.
When that happens, fall back to the local Firefox profile's Reddit cookies, exporting
only Reddit cookies to a temporary Netscape-format cookie jar that is deleted on exit.
"""

from __future__ import annotations

import atexit
import json
import os
import re
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from typing import Any
from urllib.parse import urlparse


USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"

_COOKIE_JAR: str | None = None


def _candidate_firefox_cookie_dbs() -> list[Path]:
    """Return Firefox cookies.sqlite candidates, preferring explicit env config."""
    configured = os.environ.get("REDDIT_READER_FIREFOX_PROFILE")
    if configured:
        path = Path(configured).expanduser()
        if path.is_dir():
            return [path / "cookies.sqlite"]
        return [path]

    return sorted(Path.home().glob(".mozilla/firefox/*/cookies.sqlite"))


def _export_reddit_firefox_cookies() -> str | None:
    """Export Reddit cookies from Firefox into a temporary curl cookie jar."""
    global _COOKIE_JAR

    if _COOKIE_JAR:
        return _COOKIE_JAR
    if os.environ.get("REDDIT_READER_FIREFOX_COOKIES") == "0":
        return None

    for cookie_db in _candidate_firefox_cookie_dbs():
        if not cookie_db.exists():
            continue

        try:
            conn = sqlite3.connect(f"file:{cookie_db}?mode=ro", uri=True)
            rows = conn.execute(
                """
                select host, path, isSecure, expiry, name, value
                from moz_cookies
                where host like '%reddit.com'
                """
            ).fetchall()
            conn.close()
        except sqlite3.Error:
            continue

        if not rows:
            continue

        fd, cookie_jar = tempfile.mkstemp(prefix="reddit-reader-cookies-", text=True)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write("# Netscape HTTP Cookie File\n")
            for host, path, is_secure, expiry, name, value in rows:
                include_subdomains = "TRUE" if host.startswith(".") else "FALSE"
                secure = "TRUE" if is_secure else "FALSE"
                # Some Firefox builds store millisecond expiries; curl expects seconds.
                if expiry and expiry > 10_000_000_000:
                    expiry = expiry // 1000
                handle.write(
                    "\t".join(
                        [host, include_subdomains, path, secure, str(expiry), name, value]
                    )
                    + "\n"
                )

        _COOKIE_JAR = cookie_jar
        atexit.register(_remove_cookie_jar, cookie_jar)
        return cookie_jar

    return None


def _remove_cookie_jar(cookie_jar: str) -> None:
    try:
        os.remove(cookie_jar)
    except FileNotFoundError:
        pass


def _curl(url: str, cookie_jar: str | None = None) -> subprocess.CompletedProcess[str]:
    args = [
        "curl",
        "-sS",
        "-L",
        "--fail-with-body",
        "--connect-timeout",
        "10",
        "--max-time",
        "30",
        "-H",
        f"User-Agent: {USER_AGENT}",
        "-H",
        "Accept: application/json",
    ]
    if cookie_jar:
        args.extend(["-b", cookie_jar])
    args.append(url)

    return subprocess.run(args, capture_output=True, text=True)


def _curl_effective_url(url: str, cookie_jar: str | None = None) -> subprocess.CompletedProcess[str]:
    args = [
        "curl",
        "-sS",
        "-L",
        "-o",
        "/dev/null",
        "-w",
        "%{url_effective}",
        "-H",
        f"User-Agent: {USER_AGENT}",
    ]
    if cookie_jar:
        args.extend(["-b", cookie_jar])
    args.append(url)

    return subprocess.run(args, capture_output=True, text=True)


def resolve_redirect_url(url: str) -> str:
    """Resolve Reddit short/share links, retrying with Firefox cookies if needed."""
    result = _curl_effective_url(url)
    effective = result.stdout.strip()
    if result.returncode == 0 and effective and "/s/" not in effective:
        return effective

    cookie_jar = _export_reddit_firefox_cookies()
    if cookie_jar:
        retry = _curl_effective_url(url, cookie_jar)
        effective = retry.stdout.strip()
        if retry.returncode == 0 and effective:
            return effective

    return url


def _validate_payload(data: Any, url: str) -> Any:
    """Reject API errors, challenge pages, and missing linked comments."""
    try:
        if "/comments/" not in urlparse(url).path:
            if not isinstance(data["data"]["children"], list):
                raise ValueError("invalid listing")
            return data
        post = data[0]["data"]["children"][0]
        children = data[1]["data"]["children"]
        if post["kind"] != "t3" or not post["data"]["title"] or not isinstance(children, list):
            raise ValueError("invalid post")
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise RuntimeError("Response did not contain the requested Reddit data") from error

    path = urlparse(url).path.removesuffix("/.json")
    match = re.search(r"/comments/\w+/[^/]*/(\w+)/?$", path)
    if match:
        target_id = match.group(1)
        pending = list(children)
        while pending:
            child = pending.pop()
            if child.get("kind") != "t1":
                continue
            comment = child["data"]
            if comment.get("id") == target_id:
                return data
            replies = comment.get("replies")
            if isinstance(replies, dict):
                pending.extend(replies["data"]["children"])
        raise RuntimeError(f"Response did not contain linked comment {target_id}")
    return data


def fetch_json(url: str, extra_params: str = "") -> Any:
    """Try Reddit JSON, Firefox cookies, Redlib, then browser-rendered posts."""
    json_url = url.rstrip("/") + "/.json"
    if extra_params:
        json_url += "?" + extra_params

    errors = []

    def direct(cookie_jar: str | None = None) -> Any:
        result = _curl(json_url, cookie_jar)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "curl request failed")
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError("Reddit returned HTML instead of JSON") from error
        return _validate_payload(data, json_url)

    try:
        return direct()
    except RuntimeError as error:
        errors.append(f"Reddit: {error}")

    cookie_jar = _export_reddit_firefox_cookies()
    if cookie_jar:
        try:
            return direct(cookie_jar)
        except RuntimeError as error:
            errors.append(f"Reddit with Firefox cookies: {error}")

    try:
        from redlib_fetch import fetch_compatible

        print("Reddit JSON unavailable; trying Redlib fallback.", file=sys.stderr)
        return _validate_payload(fetch_compatible(json_url), json_url)
    except RuntimeError as error:
        errors.append(f"Redlib: {error}")
        print(f"Redlib fallback failed: {error}", file=sys.stderr)

    if "/comments/" in urlparse(url).path:
        try:
            from browser_fetch import fetch_compatible as fetch_browser

            print("Trying Chromium browser fallback (public Reddit HTML).", file=sys.stderr)
            data = _validate_payload(fetch_browser(json_url), json_url)
            print("Browser output includes rendered comments only; unexpanded replies may be omitted.",
                  file=sys.stderr)
            return data
        except RuntimeError as error:
            errors.append(f"Browser: {error}")

    print("Unable to retrieve Reddit content:\n" + "\n".join(errors), file=sys.stderr)
    sys.exit(1)
