"""Shared Reddit fetching helpers.

Reddit sometimes blocks unauthenticated curl requests at the network-security layer.
When that happens, fall back to the local Firefox profile's Reddit cookies, exporting
only Reddit cookies to a temporary Netscape-format cookie jar that is deleted on exit.
"""

from __future__ import annotations

import atexit
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from typing import Any


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


def fetch_json(url: str, extra_params: str = "") -> Any:
    """Fetch Reddit JSON, then retry through Firefox cookies and Redlib."""
    json_url = url.rstrip("/") + "/.json"
    if extra_params:
        json_url += "?" + extra_params

    result = _curl(json_url)
    if result.returncode == 0:
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            pass

    cookie_jar = _export_reddit_firefox_cookies()
    if cookie_jar:
        retry = _curl(json_url, cookie_jar)
        if retry.returncode == 0:
            try:
                return json.loads(retry.stdout)
            except json.JSONDecodeError:
                pass

    # Public Redlib instances can still retrieve Reddit when its network-security
    # layer rejects direct CLI requests. Keep this last so authenticated Reddit
    # remains the preferred and most complete source.
    try:
        from redlib_fetch import fetch_compatible

        print("Reddit request blocked; using Redlib fallback.", file=sys.stderr)
        return fetch_compatible(json_url)
    except RuntimeError as error:
        response_preview = result.stdout[:200] if result.stdout else result.stderr[:200]
        print(
            f"Reddit and Redlib requests failed: {error}. "
            f"Reddit response starts with: {response_preview}",
            file=sys.stderr,
        )
        sys.exit(1)
