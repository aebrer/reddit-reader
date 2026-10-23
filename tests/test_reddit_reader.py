"""Offline regression tests; live Reddit is checked separately."""

import contextlib
import copy
import io
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import browser_fetch
import read_post
import reddit_fetch


URL = "https://old.reddit.com/r/example/comments/post/title/target/"
HTML = """
<shreddit-post id="t3_post" post-title="A post" author="poster"
 subreddit-name="example" score="42" comment-count="5"
 permalink="/r/example/comments/post/title/" content-href="https://example.com/image.png">
 <div slot="text-body"><p>First paragraph.</p><p>Second <strong>paragraph</strong>.</p></div>
</shreddit-post>
<!-- Deliberately flat and out of parent order: IDs must determine threading. -->
<shreddit-comment thingid="t1_target" parentid="t1_parent" depth="2" author="targeter" score="1">
 <details><div slot="comment"><p>The <strong>linked</strong> comment.</p><p>Another line.</p></div></details>
 <shreddit-comment-action-row is-score-hidden></shreddit-comment-action-row>
</shreddit-comment>
<shreddit-comment thingid="t1_root" depth="0" author="rooter" score="10">
 <div slot="comment"><p>Root comment.</p></div>
 <shreddit-comment-action-row score="10"></shreddit-comment-action-row>
</shreddit-comment>
<shreddit-comment thingid="t1_reply" parentid="t1_target" depth="3" author="replier" score="2">
 <div slot="comment"><p>Reply to target.</p><script>not content</script></div>
 <shreddit-comment-action-row score="2"></shreddit-comment-action-row>
</shreddit-comment>
<shreddit-comment thingid="t1_parent" parentid="t1_root" depth="1" author="parenter" score="5">
 <div slot="comment"><p>Parent comment.</p></div>
 <shreddit-comment-action-row score="5"></shreddit-comment-action-row>
</shreddit-comment>
<shreddit-comment thingid="t1_other" depth="0" author="other" score="3">
 <div slot="comment"><p>Unrelated root.</p></div>
</shreddit-comment>
"""


def comments(data):
    return data[1]["data"]["children"]


def replies(comment):
    return comment["data"]["replies"]["data"]["children"]


class BrowserParserTests(unittest.TestCase):
    def test_reconstructs_tree_using_ids_not_dom_order(self):
        data = browser_fetch.parse_post_html(HTML)
        roots = comments(data)
        self.assertEqual([c["data"]["id"] for c in roots], ["root", "other"])
        parent = replies(roots[0])[0]
        target = replies(parent)[0]
        reply = replies(target)[0]
        self.assertEqual(parent["data"]["id"], "parent")
        self.assertEqual(target["data"]["id"], "target")
        self.assertEqual(target["data"]["parent_id"], "t1_parent")
        self.assertEqual(reply["data"]["id"], "reply")
        self.assertEqual(reply["data"]["depth"], 3)

    def test_rendering_preserves_threading_highlight_and_paragraphs(self):
        data = browser_fetch.parse_post_html(HTML)
        lines = read_post.extract_comments(comments(data), 99, "target")
        self.assertTrue(lines[0].startswith("[10] u/rooter:"))
        self.assertTrue(lines[1].startswith("  [5] u/parenter:"))
        self.assertEqual(lines[2], "    [?] u/targeter: The linked comment.\n      \n      Another line. <<<")
        self.assertEqual(lines[3], "      [2] u/replier: Reply to target.")
        self.assertNotIn("not content", "\n".join(lines))
        self.assertEqual(len(read_post.extract_comments(comments(data), 1)), 3)

    def test_negative_page_depths_are_rebuilt_from_parent_ids(self):
        html = HTML.replace('depth="0"', 'depth="-2"').replace('depth="1"', 'depth="-1"')
        roots = comments(browser_fetch.parse_post_html(html))
        self.assertEqual(roots[0]["data"]["depth"], 0)
        self.assertEqual(replies(roots[0])[0]["data"]["depth"], 1)
        self.assertEqual(replies(replies(roots[0])[0])[0]["data"]["depth"], 2)

    def test_absent_vote_controls_mean_score_unknown(self):
        html = HTML.replace('<shreddit-comment-action-row score="10"></shreddit-comment-action-row>', '')
        self.assertIsNone(comments(browser_fetch.parse_post_html(html))[0]["data"]["score"])

    def test_post_fields_and_body(self):
        post = browser_fetch.parse_post_html(HTML)[0]["data"]["children"][0]["data"]
        self.assertEqual(post["selftext"], "First paragraph.\n\nSecond paragraph.")
        self.assertEqual(post["num_comments"], 5)
        self.assertEqual(post["score"], 42)
        self.assertIn("LINK: https://example.com/image.png", read_post.format_post(post))

    def test_nested_dom_does_not_duplicate_replies_or_steal_body(self):
        html = """<shreddit-post id="t3_post" post-title="Title" comment-count="2"></shreddit-post>
        <shreddit-comment thingid="t1_root" author="root" depth="0">
          <details><div slot="comment"><p>Root only.</p></div>
            <div><shreddit-comment thingid="t1_child" parentid="t1_root" depth="1">
              <div slot="comment"><p>Child only.</p></div>
            </shreddit-comment></div>
          </details>
        </shreddit-comment>"""
        roots = comments(browser_fetch.parse_post_html(html))
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0]["data"]["body"], "Root only.")
        self.assertEqual(replies(roots[0])[0]["data"]["body"], "Child only.")
        self.assertEqual(len(replies(roots[0])), 1)

    def test_missing_body_cannot_be_replaced_by_child_body(self):
        html = """<shreddit-post post-title="Title"></shreddit-post>
        <shreddit-comment thingid="t1_root">
          <shreddit-comment thingid="t1_child" parentid="t1_root">
            <div slot="comment">Child only.</div>
          </shreddit-comment>
        </shreddit-comment>"""
        with self.assertRaisesRegex(RuntimeError, "without its body"):
            browser_fetch.parse_post_html(html)

    def test_challenge_page_is_not_a_successful_post(self):
        with self.assertRaisesRegex(RuntimeError, "no Reddit post"):
            browser_fetch.parse_post_html("<html><h1>Verifying your browser</h1></html>")

    def test_missing_playwright_has_setup_instructions(self):
        failure = subprocess.CompletedProcess([], 1, "", "Cannot find module 'playwright'")
        with patch("browser_fetch.subprocess.run", return_value=failure):
            with self.assertRaisesRegex(RuntimeError, "npm ci"):
                browser_fetch.fetch_compatible(URL + ".json?context=10")

    def test_browser_url_preserves_context_and_normalizes_host(self):
        result = subprocess.CompletedProcess([], 0, HTML, "")
        with patch("browser_fetch.subprocess.run", return_value=result) as run:
            browser_fetch.fetch_compatible(URL + ".json?context=10")
        self.assertEqual(run.call_args.args[0][-1],
                         "https://www.reddit.com/r/example/comments/post/title/target?context=10")


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.data = browser_fetch.parse_post_html(HTML)
        self.html_response = subprocess.CompletedProcess([], 0, "<html>blocked</html>", "")

    def test_api_errors_and_missing_targets_are_rejected(self):
        for data in ({"error": 403}, [], {"data": {"children": []}}):
            with self.subTest(data=data):
                with self.assertRaises(RuntimeError):
                    reddit_fetch._validate_payload(data, URL)
        missing = copy.deepcopy(self.data)
        replies(comments(missing)[0])[0]["data"]["replies"]["data"]["children"] = []
        with self.assertRaisesRegex(RuntimeError, "linked comment target"):
            reddit_fetch._validate_payload(missing, URL)

    def test_successful_json_does_not_launch_fallbacks(self):
        import json
        result = subprocess.CompletedProcess([], 0, json.dumps(self.data), "")
        with patch("reddit_fetch._curl", return_value=result), \
             patch("redlib_fetch.fetch_compatible") as redlib, \
             patch("browser_fetch.fetch_compatible") as browser:
            self.assertEqual(reddit_fetch.fetch_json(URL), self.data)
        redlib.assert_not_called()
        browser.assert_not_called()

    def test_firefox_retry_before_fallback(self):
        import json
        result = subprocess.CompletedProcess([], 0, json.dumps(self.data), "")
        with patch("reddit_fetch._curl", side_effect=[self.html_response, result]) as curl, \
             patch("reddit_fetch._export_reddit_firefox_cookies", return_value="jar"), \
             patch("redlib_fetch.fetch_compatible") as redlib:
            self.assertEqual(reddit_fetch.fetch_json(URL), self.data)
        self.assertEqual(curl.call_args.args[1], "jar")
        redlib.assert_not_called()

    def test_redlib_missing_target_triggers_browser(self):
        missing = copy.deepcopy(self.data)
        missing[1]["data"]["children"] = []
        stderr = io.StringIO()
        with patch("reddit_fetch._curl", return_value=self.html_response), \
             patch("reddit_fetch._export_reddit_firefox_cookies", return_value=None), \
             patch("redlib_fetch.fetch_compatible", return_value=missing), \
             patch("browser_fetch.fetch_compatible", return_value=self.data), \
             contextlib.redirect_stderr(stderr):
            self.assertEqual(reddit_fetch.fetch_json(URL, "context=10"), self.data)
        self.assertIn("linked comment target", stderr.getvalue())
        self.assertIn("Chromium", stderr.getvalue())

    def test_all_backends_fail_loudly(self):
        with patch("reddit_fetch._curl", return_value=self.html_response), \
             patch("reddit_fetch._export_reddit_firefox_cookies", return_value=None), \
             patch("redlib_fetch.fetch_compatible", side_effect=RuntimeError("Redlib 404")), \
             patch("browser_fetch.fetch_compatible", side_effect=RuntimeError("Browser blocked")), \
             contextlib.redirect_stderr(io.StringIO()) as stderr:
            with self.assertRaises(SystemExit) as exit_info:
                reddit_fetch.fetch_json(URL)
        self.assertEqual(exit_info.exception.code, 1)
        self.assertIn("Redlib 404", stderr.getvalue())
        self.assertIn("Browser blocked", stderr.getvalue())

    def test_listing_keeps_existing_redlib_fallback(self):
        listing = {"data": {"children": []}}
        with patch("reddit_fetch._curl", return_value=self.html_response), \
             patch("reddit_fetch._export_reddit_firefox_cookies", return_value=None), \
             patch("redlib_fetch.fetch_compatible", return_value=listing), \
             patch("browser_fetch.fetch_compatible") as browser, \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(reddit_fetch.fetch_json("https://old.reddit.com/r/example/"), listing)
        browser.assert_not_called()

    def test_modern_and_old_comment_links(self):
        for slug in ("title", "comment"):
            url = f"https://www.reddit.com/r/example/comments/post/{slug}/target/?context=2"
            normalized = read_post.resolve_url(url)
            self.assertEqual(read_post.detect_comment_id(normalized), "target")
            self.assertIs(reddit_fetch._validate_payload(self.data, normalized), self.data)


if __name__ == "__main__":
    unittest.main()
