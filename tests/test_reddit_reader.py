"""Offline tests for the single GraphQL transport, pagination, and CLI output."""

import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from curl_cffi.requests.exceptions import Timeout
import read_post
import read_subreddit
import reddit_fetch as rf
import search_subreddit

URL = "https://www.reddit.com/r/example/comments/post/title/target/"


def post_node(post_id="post", subreddit="example", **extra):
    return dict({"__typename": "SubredditPost", "id": "t3_" + post_id, "postTitle": "A post",
                 "authorInfo": {"name": "poster"}, "score": 42, "commentCount": 5,
                 "subreddit": {"name": subreddit}, "content": {"markdown": "First.\n\nSecond."},
                 "permalink": f"/r/{subreddit}/comments/{post_id}/title/"}, **extra)


def comment(key, parent=None, depth=0, **extra):
    return {"depth": depth, "parentId": parent, "more": None,
            "node": dict({"__typename": "Comment", "id": "t1_" + key,
                          "authorInfo": {"name": key + "er"}, "score": 2,
                          "content": {"markdown": key + " body"}}, **extra)}


def more(cursor, parent=None, depth=0):
    return {"depth": depth, "parentId": parent, "node": None,
            "more": {"cursor": cursor, "count": 5}}


def forest(trees):
    return {"postInfoById": {"id": "t3_post", "commentForest": {"trees": trees}}}


def connection(nodes, cursor=None):
    return {"edges": [{"node": n} for n in nodes],
            "pageInfo": {"hasNextPage": cursor is not None, "endCursor": cursor}}


def listing(nodes, cursor=None):
    return {"postFeed": {"__typename": "Subreddit", "elements": connection(nodes, cursor)}}


def search_result(nodes, cursor=None):
    return {"search": {"general": {"posts": connection(nodes, cursor)}}}


def response(data=None, status=200, headers=None):
    return Mock(status_code=status, headers=headers or {}, json=Mock(return_value=data))


def children(child):
    return child["data"]["replies"]["data"]["children"]


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.client = rf.RedditClient()
        self.addCleanup(self.client.session.close)
        self.request = Mock()
        self.client.session.request = self.request
        self.auth = response({"access_token": "private-token", "expires_in": 3600},
                             headers={"x-reddit-loid": "anon-device", "x-reddit-session": "anon-session"})

    def test_tls_session_and_ephemeral_device_headers(self):
        self.assertEqual(self.client.session.impersonate, "chrome")
        headers = self.client.session.headers
        self.assertEqual(headers["User-Agent"], rf.APP_USER_AGENT)
        self.assertEqual(headers["client-vendor-id"], headers["X-Reddit-Device-Id"])
        self.assertNotIn("Authorization", headers)

    def test_authentication_query_shape_and_token_reuse(self):
        self.request.side_effect = [self.auth, response({"data": {"ok": 1}}), response({"data": {"ok": 2}})]
        self.assertEqual(self.client.query("PostComments", {"id": "t3_post"}), {"ok": 1})
        self.client.query("PostsByIds", {"ids": ["t3_post"]})
        self.assertEqual(self.request.call_count, 3)
        auth = self.request.call_args_list[0]
        self.assertEqual(auth.args, ("POST", rf.AUTH_URL))
        self.assertEqual(auth.kwargs["auth"], (rf.APP_ID, ""))
        query = self.request.call_args_list[1]
        self.assertEqual(query.args, ("POST", rf.GQL_URL))
        self.assertEqual(query.kwargs["headers"]["Authorization"], "Bearer private-token")
        self.assertEqual(query.kwargs["headers"]["x-reddit-loid"], "anon-device")
        self.assertEqual(query.kwargs["json"]["extensions"]["persistedQuery"],
                         {"version": 1, "sha256Hash": rf.OPERATIONS["PostComments"]})
        self.assertEqual(query.kwargs["timeout"], 30)
        self.assertFalse(query.kwargs["allow_redirects"])

    def test_expired_token_refreshes_same_transport(self):
        self.request.side_effect = [self.auth, response({"data": {}}), self.auth, response({"data": {}})]
        self.client.query("PostComments", {})
        self.client.expires_at = 0
        self.client.query("PostComments", {})
        self.assertEqual([c.args[1] for c in self.request.call_args_list],
                         [rf.AUTH_URL, rf.GQL_URL, rf.AUTH_URL, rf.GQL_URL])

    def test_http_errors_fail_without_other_transports(self):
        for status in (401, 403, 429, 500):
            with self.subTest(status=status):
                self.client.expires_at = float("inf")
                self.request.reset_mock()
                self.request.side_effect = None
                self.request.return_value = response(status=status)
                with self.assertRaisesRegex(rf.RedditError, f"HTTP {status}"):
                    self.client.query("PostComments", {})
                self.assertEqual(self.request.call_count, 1)

    def test_timeout_has_actionable_sanitized_error(self):
        self.request.side_effect = Timeout("Authorization: Bearer private-token")
        with self.assertRaisesRegex(rf.RedditError, "network request failed") as raised:
            self.client.query("PostComments", {})
        self.assertNotIn("private-token", str(raised.exception))

    def test_non_json_invalid_json_and_redirect_are_errors(self):
        html = response()
        html.json.side_effect = ValueError("HTML")
        for result in (html, response([]), response(status=302)):
            with self.subTest(result=result):
                self.request.side_effect = [result]
                with self.assertRaises(rf.RedditError):
                    self.client.query("PostComments", {})

    def test_graphql_errors_reject_partial_data(self):
        self.request.side_effect = [self.auth, response({"data": {"postInfoById": {}},
            "errors": [{"extensions": {"code": "DEPENDENCY_FAILURE"}}]})]
        with self.assertRaisesRegex(rf.RedditError, "DEPENDENCY_FAILURE.*no partial data"):
            self.client.query("PostComments", {})

    def test_missing_data_and_token_are_errors(self):
        for token in ({}, {"access_token": "t", "expires_in": 0}):
            self.request.side_effect = [response(token)]
            with self.assertRaisesRegex(rf.RedditError, "session token"):
                self.client.query("PostComments", {})
        self.request.side_effect = [self.auth, response({"data": None})]
        with self.assertRaisesRegex(rf.RedditError, "missing GraphQL data"):
            self.client.query("PostComments", {})

    def test_context_manager_closes_session(self):
        with patch.object(self.client.session, "close") as close:
            with self.client:
                pass
        close.assert_called_once()


class URLTests(unittest.TestCase):
    def setUp(self):
        self.client = rf.RedditClient()
        self.addCleanup(self.client.session.close)

    def test_post_comment_short_and_query_links(self):
        for url, expected in (
            (URL + "?context=2#target", ("post", "target")),
            (URL.replace("www.", "old."), ("post", "target")),
            ("https://reddit.com/comments/post/title/target", ("post", "target")),
            ("https://reddit.com/r/example/comments/post/", ("post", None)),
            ("https://reddit.com/r/example/comments/post/title/", ("post", None)),
            ("https://redd.it/post", ("post", None)),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.post_ids(url), expected)

    def test_share_redirect_uses_same_session_without_bearer(self):
        with patch.object(self.client.session, "request", return_value=response(status=302, headers={"location": URL})) as request:
            self.assertEqual(self.client.post_ids("https://reddit.com/r/example/s/short"), ("post", "target"))
        self.assertNotIn("headers", request.call_args.kwargs)

    def test_share_cannot_redirect_off_reddit_or_succeed_unresolved(self):
        for result in (response(status=302, headers={"location": "https://evil.test/"}), response({})):
            with patch.object(self.client.session, "request", return_value=result):
                with self.assertRaises(rf.RedditError):
                    self.client.post_ids("https://reddit.com/r/example/s/short")

    def test_share_redirect_loop_is_bounded(self):
        with patch.object(self.client.session, "request", return_value=response(status=302, headers={"location": "/r/example/s/short"})) as request:
            with self.assertRaises(rf.RedditError):
                self.client.post_ids("https://reddit.com/r/example/s/short")
        self.assertEqual(request.call_count, 6)

    def test_reject_invalid_url_and_subreddit_before_network(self):
        for value in ("https://reddit.com.evil.test/r/x/", "file:///etc/passwd", "https://user@reddit.com/",
                      "https://reddit.com:invalid/r/x/", "https://reddit.com:8080/r/x/"):
            with self.subTest(value=value), self.assertRaises(rf.RedditError):
                rf.checked_url(value)
        for value in ("example", "r/example", "https://old.reddit.com/r/example/new/?x=1"):
            self.assertEqual(rf.normalize_subreddit(value), "example")
        for value in ("x/y", "x?limit=10", "https://evil.test/r/example"):
            with self.assertRaises(rf.RedditError):
                rf.normalize_subreddit(value)


class TreeTests(unittest.TestCase):
    def test_ids_not_page_order_determine_threading(self):
        tree = rf.CommentTree("post")
        tree.add([comment("target", "t1_parent", 0), comment("root"),
                  comment("reply", "t1_target", 2), comment("parent", "t1_root", 1), comment("other")])
        roots = tree.render()
        self.assertEqual([c["data"]["id"] for c in roots], ["root", "other"])
        self.assertEqual(children(children(children(roots[0])[0])[0])[0]["data"]["id"], "reply")
        linked = tree.render("t1_target")
        self.assertEqual(len(linked), 1)
        self.assertEqual(children(linked[0])[0]["data"]["depth"], 1)
        self.assertNotIn("otherer", "\n".join(read_post.extract_comments(linked, 99)))

    def test_deleted_parents_keep_descendants(self):
        tree = rf.CommentTree("post")
        tree.add([comment("root"), {"depth": 1, "parentId": "t1_root",
                  "node": {"__typename": "DeletedComment"}}, comment("reply", "t1_missing", 2)])
        deleted = children(tree.render()[0])[0]
        self.assertEqual(deleted["data"]["body"], "[deleted]")
        self.assertEqual(children(deleted)[0]["data"]["id"], "reply")

    def test_deleted_parent_identity_survives_continuation(self):
        tree = rf.CommentTree("post")
        tree.add([comment("root"), {"depth": 1, "parentId": "t1_root",
                  "node": {"__typename": "DeletedComment"}}, more("deep", "t1_deleted", 2)])
        tree.add([comment("reply", "t1_deleted")])
        deleted = children(tree.render()[0])[0]
        self.assertEqual(deleted["data"]["id"], "deleted")
        self.assertEqual(children(deleted)[0]["data"]["id"], "reply")

    def test_focused_deleted_root_has_requested_identity(self):
        tree = rf.CommentTree("post")
        tree.add([comment("reply", "t1_deleted")])
        tree.add([{"depth": 0, "parentId": None, "node": {"__typename": "DeletedComment"}}],
                 focus="t1_deleted")
        deleted = tree.render()[0]
        self.assertEqual(deleted["data"]["id"], "deleted")
        self.assertEqual(children(deleted)[0]["data"]["id"], "reply")

    def test_duplicates_merge_and_page_depth_does_not_change_parent(self):
        tree = rf.CommentTree("post")
        tree.add([comment("root"), comment("child", "t1_root", 1)])
        tree.add([comment("child", "t1_root", 0), comment("reply", "t1_child", 1)])
        root = tree.render()[0]
        self.assertEqual(len(children(root)), 1)
        self.assertEqual(children(children(root)[0])[0]["data"]["depth"], 2)

    def test_malformed_missing_and_cyclic_parents_fail(self):
        for entries in ([comment("a", "t1_a")], [comment("a", "t1_b"), comment("b", "t1_a")],
                        [comment("orphan", "t1_absent")]):
            tree = rf.CommentTree("post")
            tree.add(entries)
            with self.assertRaises(rf.RedditError):
                tree.render()
        for entry in (comment("a", content={}), comment('bad"'), {"depth": -1}, more("")):
            with self.assertRaises(rf.RedditError):
                rf.CommentTree("post").add([entry])

    def test_score_removal_and_paragraphs(self):
        tree = rf.CommentTree("post")
        tree.add([comment("target", isScoreHidden=True, content={"markdown": "One.\n\nTwo."}),
                  comment("removed", isRemoved=True)])
        lines = read_post.extract_comments(tree.render(), 0, "target")
        self.assertEqual(lines[0], "[?] u/targeter: One.\n  \n  Two. <<<")
        self.assertIn("[removed]", lines[1])


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.client = rf.RedditClient()
        self.addCleanup(self.client.session.close)
        self.query = Mock()
        self.client.query = self.query
        self.post = {"postsInfoByIds": [post_node()]}

    def test_deep_link_fetches_target_and_missing_ancestors(self):
        self.query.side_effect = [self.post, forest([comment("root"), comment("other")]),
            forest([comment("target", "t1_parent")]), forest([comment("parent", "t1_root")])]
        result = self.client.read_post(URL)
        lines = read_post.extract_comments(result.linked_comments, 99, result.comment_id)
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[-1].endswith("<<<"))
        self.assertNotIn("otherer", "\n".join(lines))
        focuses = [c.args[1].get("focusedCommentContext") for c in self.query.call_args_list[1:]]
        self.assertEqual(focuses[1]["commentId"], "t1_target")
        self.assertEqual(focuses[2]["commentId"], "t1_parent")

    def test_missing_linked_comment_and_parent_fail(self):
        for focused in ([], [comment("target", "t1_missing")]):
            self.query.side_effect = [self.post, forest([comment("root")]), forest(focused), forest([])]
            with self.assertRaisesRegex(rf.RedditError, "linked comment/ancestor"):
                self.client.read_post(URL)

    def test_ancestry_budget_fails_instead_of_printing_disconnected_comment(self):
        self.query.side_effect = [self.post, forest([comment("root")])]
        with self.assertRaisesRegex(rf.RedditError, "ancestry exceeded --max-pages"):
            self.client.read_post(URL, max_pages=1)

    def test_nested_cursor_uses_after_without_focused_context(self):
        self.query.side_effect = [self.post, forest([comment("root"), more("opaque", "t1_root", 1)]),
                                 forest([comment("target", "t1_root")])]
        result = self.client.read_post(URL.replace("target/", ""), depth=1)
        self.assertEqual(children(result.comments[0])[0]["data"]["id"], "target")
        variables = self.query.call_args.args[1]
        self.assertEqual(variables["after"], "opaque")
        self.assertNotIn("focusedCommentContext", variables)

    def test_depth_and_root_limit_avoid_unneeded_pages(self):
        self.query.side_effect = [self.post, forest([comment("root"), comment("other"),
            more("nested", "t1_root", 1), more("top")])]
        self.client.read_post(URL.replace("target/", ""), depth=0, limit=1)
        self.assertEqual(self.query.call_count, 2)

    def test_linked_replies_ignore_broader_thread_depth_limit(self):
        self.query.side_effect = [self.post, forest([comment("root"), comment("target", "t1_root", 1),
            more("nested", "t1_target", 2)]), forest([comment("reply", "t1_target")])]
        result = self.client.read_post(URL, depth=0)
        self.assertEqual(len(read_post.extract_comments(result.linked_comments, 99)), 3)

    def test_page_budget_warns_for_omitted_replies(self):
        self.query.side_effect = [self.post, forest([comment("root"), more("next")])]
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.client.read_post(URL.replace("target/", ""), limit=0, max_pages=1)
        self.assertIn("additional replies are omitted", stderr.getvalue())

    def test_repeated_comment_cursor_is_an_error(self):
        self.query.side_effect = [self.post, forest([comment("root"), more("same")]), forest([more("same")])]
        with self.assertRaisesRegex(rf.RedditError, "repeated comment cursor"):
            self.client.read_post(URL.replace("target/", ""), limit=0)

    def test_empty_thread_is_success(self):
        self.query.side_effect = [{"postsInfoByIds": [post_node(commentCount=0)]}, forest([])]
        result = self.client.read_post("https://redd.it/post")
        self.assertEqual(result.comments, [])

    def test_metadata_and_comment_response_identity_are_checked(self):
        for metadata in ({"postsInfoByIds": []}, {"postsInfoByIds": [post_node("wrong")]}):
            self.query.side_effect = [metadata]
            with self.assertRaisesRegex(rf.RedditError, "requested post"):
                self.client.read_post(URL)
        self.query.side_effect = [self.post, {"postInfoById": {"id": "t3_wrong"}}]
        with self.assertRaisesRegex(rf.RedditError, "requested comment thread"):
            self.client.read_post(URL)
        self.query.side_effect = [self.post, {"postInfoById": {"id": "t3_post"}}]
        with self.assertRaisesRegex(rf.RedditError, "comment forest"):
            self.client.read_post(URL)

    def test_listing_cursor_paging_deduplicates_and_replaces_stickies(self):
        self.query.side_effect = [listing([post_node("sticky", isStickied=True), post_node("a")], "opaque"),
                                 listing([post_node("a"), post_node("b")])]
        self.assertEqual([p["id"] for p in self.client.subreddit("r/example", limit=2)], ["a", "b"])
        self.assertEqual(self.query.call_args.args[1]["after"], "opaque")

    def test_popular_feed_uses_post_info(self):
        self.query.return_value = {"popular": {"elements": connection([{"postInfo": post_node()}])}}
        self.assertEqual(self.client.subreddit("popular", limit=1)[0]["id"], "post")
        self.assertEqual(self.query.call_args.args[0], "PopularFeedElements")

    def test_all_feed_fetches_organic_ids_in_feed_order(self):
        self.query.side_effect = [{"allV3": {"elements": connection([
            {"groupId": "sortcell"}, {"groupId": "t3_b"},
            {"groupId": "t3_ad", "adPayload": {"tracking": True}}, {"groupId": "t3_a"}])}},
            {"postsInfoByIds": [post_node("a"), post_node("b")]}]
        self.assertEqual([p["id"] for p in self.client.subreddit("all", limit=2)], ["b", "a"])
        self.assertEqual(self.query.call_args_list[0].args[0], "AllFeedSdui")
        self.assertEqual(self.query.call_args.args[1]["ids"], ["t3_b", "t3_a"])

    def test_search_is_scoped_and_paginates_with_after_cursor(self):
        self.query.side_effect = [search_result([post_node("a")], "next"), search_result([post_node("b")])]
        self.assertEqual(len(self.client.search("Example", "cats OR dogs", limit=2)), 2)
        variables = self.query.call_args.args[1]
        self.assertEqual(variables["query"], "subreddit:Example (cats OR dogs)")
        self.assertEqual(variables["afterCursor"], "next")
        self.assertEqual(variables["sort"], "NEW")
        self.assertIn({"key": "time_range", "value": "year"}, variables["filters"])

    def test_search_rejects_results_from_wrong_subreddit(self):
        self.query.return_value = search_result([post_node(subreddit="elsewhere")])
        with self.assertRaisesRegex(rf.RedditError, "outside the requested subreddit"):
            self.client.search("example", "cats", limit=1)

    def test_empty_listing_search_and_unavailable_subreddit(self):
        self.query.side_effect = [listing([]), search_result([]), {"postFeed": {"__typename": "UnavailableSubreddit"}}]
        self.assertEqual(self.client.subreddit("example"), [])
        self.assertEqual(self.client.search("example", "no results"), [])
        with self.assertRaisesRegex(rf.RedditError, "accessible subreddit"):
            self.client.subreddit("example")

    def test_repeated_or_missing_listing_cursor_is_an_error(self):
        self.query.side_effect = [listing([], "same"), listing([], "same")]
        with self.assertRaisesRegex(rf.RedditError, "repeated listing cursor"):
            self.client.subreddit("example")
        self.query.return_value = {"postFeed": {"__typename": "Subreddit", "elements": {"edges": []}}}
        self.query.side_effect = None
        with self.assertRaisesRegex(rf.RedditError, "missing or repeated listing cursor"):
            self.client.subreddit("example")

    def test_post_metadata_fields_and_tracking_destination(self):
        node = post_node(outboundLink={"url": "https://out.reddit.com/x?url=https%3A%2F%2Fexample.com%2F"})
        post = rf.convert_post(node)
        self.assertIn("LINK: https://example.com/", read_post.format_post(post))
        self.assertIn("First.\n\nSecond.", read_post.format_post(post))
        listing_node = post_node(title="Feed title", isScoreHidden=True)
        self.assertIn("[?] Feed title", read_subreddit.format_post(rf.convert_post(listing_node), 1))


class CLITests(unittest.TestCase):
    def test_linked_rendering_and_broader_filters(self):
        tree = rf.CommentTree("post")
        tree.add([comment("root"), comment("target", "t1_root", 1), comment("other")])
        result = rf.PostResult(rf.convert_post(post_node()), tree.render(), tree.render("t1_target"), "target")
        with patch("sys.argv", ["read_post", URL, "--depth", "0", "--limit", "1"]), \
             patch("read_post.RedditClient") as client, contextlib.redirect_stdout(io.StringIO()) as out:
            client.return_value.__enter__.return_value.read_post.return_value = result
            read_post.main()
        linked, full = out.getvalue().split("=== FULL THREAD")
        self.assertIn("target body <<<", linked)
        self.assertNotIn("target body", full)
        self.assertNotIn("other body", full)

    def test_listing_and_search_commands_format_results(self):
        for module, argv, method in ((read_subreddit, ["read_subreddit", "r/example"], "subreddit"),
                                     (search_subreddit, ["search_subreddit", "example", "cats"], "search")):
            with patch("sys.argv", argv), patch.object(module, "RedditClient") as client, \
                 contextlib.redirect_stdout(io.StringIO()) as out:
                getattr(client.return_value.__enter__.return_value, method).return_value = [rf.convert_post(post_node())]
                module.main()
            self.assertIn("1. [42] A post", out.getvalue())

    def test_failures_exit_nonzero_without_success_output(self):
        with patch("sys.argv", ["read_post", URL]), patch("read_post.RedditClient", side_effect=rf.RedditError("blocked")), \
             contextlib.redirect_stderr(io.StringIO()) as err, contextlib.redirect_stdout(io.StringIO()) as out:
            with self.assertRaises(SystemExit) as raised:
                read_post.main()
        self.assertEqual(raised.exception.code, 1)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("blocked", err.getvalue())

    def test_invalid_limits_rejected_before_client_creation(self):
        for module, argv in ((read_post, ["read_post", URL, "--depth", "-1"]),
                             (read_post, ["read_post", URL, "--max-pages", "0"]),
                             (read_subreddit, ["read_subreddit", "example", "--limit", "0"]),
                             (search_subreddit, ["search_subreddit", "example", "cats", "--limit", "-1"])):
            with patch("sys.argv", argv), patch.object(module, "RedditClient") as client, \
                 contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    module.main()
                self.assertEqual(raised.exception.code, 2)
                client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
