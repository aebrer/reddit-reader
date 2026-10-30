"""Opt-in network tests: REDDIT_READER_LIVE=1 .venv/bin/python -m unittest discover -s tests -v."""

import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from reddit_fetch import RedditClient

POST = "https://www.reddit.com/r/pebble/comments/1xj4whi/pebbleos_linux_port_for_android_smartwatches/"
COMMENT = "19rvrf30azfk3"


@unittest.skipUnless(os.environ.get("REDDIT_READER_LIVE") == "1", "set REDDIT_READER_LIVE=1 for network tests")
class LiveTests(unittest.TestCase):
    def run_cli(self, name, *args):
        return subprocess.run([sys.executable, str(ROOT / "scripts" / name), *args],
                              text=True, capture_output=True, timeout=180)

    def test_linked_comment_cli_includes_parent_chain(self):
        result = self.run_cli("read_post.py", POST + COMMENT + "/")
        self.assertEqual(result.returncode, 0, result.stderr)
        linked = result.stdout.split("=== FULL THREAD")[0]
        self.assertIn(f"=== LINKED THREAD (comment {COMMENT}) ===", linked)
        self.assertIn("<<<", linked)
        self.assertIn("is the batery life better than stock?", linked)
        self.assertIn("LINK: https://github.com/brosiog/pebbleos-linux", linked)
        self.assertGreaterEqual(sum(line.lstrip().startswith("[") for line in linked.splitlines()), 11)

    def test_short_post_link_and_deep_continuation(self):
        result = self.run_cli("read_post.py", "https://redd.it/1xj4whi", "--depth", "12", "--limit", "0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Bad faith? It's a good faith only if I agree?", result.stdout)
        self.assertNotIn("--max-pages", result.stderr)

    def test_subreddit_listing_sorts(self):
        for sort in ("hot", "new", "top", "rising"):
            with self.subTest(sort=sort):
                result = self.run_cli("read_subreddit.py", "https://reddit.com/r/pebble/", "--sort", sort, "--limit", "3")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"r/pebble — {sort}", result.stdout)
                # A rising feed may genuinely contain fewer than three posts.
                if sort != "rising":
                    self.assertIn("3. [", result.stdout)

    def test_aggregate_feeds(self):
        for subreddit in ("all", "popular"):
            with self.subTest(subreddit=subreddit):
                result = self.run_cli("read_subreddit.py", subreddit, "--limit", "3")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("3. [", result.stdout)

    def test_linked_comment_below_deleted_parent(self):
        result = self.run_cli("read_post.py", "https://reddit.com/comments/j1wrzl/x/g723u6w/", "--max-pages", "10", "--limit", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        linked = result.stdout.split("=== FULL THREAD")[0]
        self.assertIn("[deleted]", linked)
        self.assertIn("<<<", linked)

    def test_feed_and_search_pagination(self):
        with RedditClient() as client:
            with patch.object(client, "query", wraps=client.query) as query:
                posts = client.subreddit("pebble", "new", 105)
                self.assertGreaterEqual(query.call_count, 2)
            self.assertEqual(len(posts), 105)
            self.assertEqual(len({p["id"] for p in posts}), 105)
            with patch.object(client, "query", wraps=client.query) as query:
                posts = client.search("pebble", "pebble", time_range="all", limit=105)
                self.assertGreaterEqual(query.call_count, 2)
            self.assertEqual(len(posts), 105)
            self.assertTrue(all(p["subreddit"].lower() == "pebble" for p in posts))

    def test_search_cli_is_scoped(self):
        result = self.run_cli("search_subreddit.py", "pebble", "linux", "--limit", "3")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count("https://reddit.com/r/pebble/comments/"), 3)

    def test_empty_search_is_success(self):
        result = self.run_cli("search_subreddit.py", "pebble", "rr_nonexistent_6aac63ddef5b4c61", "--limit", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("1. [", result.stdout)

    def test_zero_comment_post(self):
        with RedditClient() as client:
            posts = client.subreddit("pebble", "new", 30)
            empty = next((post for post in posts if post["num_comments"] == 0), None)
            if empty is None:
                self.skipTest("no recent zero-comment post available")
            result = client.read_post("https://reddit.com" + empty["permalink"])
            self.assertEqual(result.comments, [])

    def test_missing_linked_comment_fails_without_partial_output(self):
        result = self.run_cli("read_post.py", POST + "zzzzzzzzzzzzzzzzzz/")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unable to retrieve Reddit content", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
