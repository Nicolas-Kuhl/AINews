"""Tests for the pure logic of segment-backdrop screenshots (no Playwright/PIL)."""

from __future__ import annotations

import os
import unittest

from ainews.video.screenshots import is_degenerate, is_screenshotable


class ScreenshotableTests(unittest.TestCase):
    def test_http_urls_ok(self):
        self.assertTrue(is_screenshotable("https://openai.com/index/x"))
        self.assertTrue(is_screenshotable("http://example.com/a"))

    def test_non_http_rejected(self):
        self.assertFalse(is_screenshotable("newsletter://Futuretools.io/123#0"))
        self.assertFalse(is_screenshotable("ftp://x.com/a"))
        self.assertFalse(is_screenshotable(""))
        self.assertFalse(is_screenshotable("not a url"))

    def test_missing_host_rejected(self):
        self.assertFalse(is_screenshotable("https://"))


class DegenerateTests(unittest.TestCase):
    def test_normal_page_kept(self):
        # A real article: varied content, mid brightness
        self.assertFalse(is_degenerate(mean_brightness=140.0, stddev=55.0))

    def test_blank_white_rejected(self):
        self.assertTrue(is_degenerate(mean_brightness=252.0, stddev=4.0))

    def test_uniform_overlay_rejected(self):
        # A solid consent overlay: low variance even if not white
        self.assertTrue(is_degenerate(mean_brightness=80.0, stddev=6.0))

    def test_mostly_white_rejected_even_with_some_variance(self):
        self.assertTrue(is_degenerate(mean_brightness=242.0, stddev=30.0))

    def test_dark_but_varied_kept(self):
        # A dark-themed site with real content
        self.assertFalse(is_degenerate(mean_brightness=40.0, stddev=42.0))




class _FakeResponse:
    def __init__(self, status=200, headers=None):
        self.status = status
        self.headers = headers or {}


class _FakeRoute:
    """Stands in for playwright Route: records what the guard decided."""

    def __init__(self, url: str, response: "_FakeResponse | None" = None):
        self.request = type("Req", (), {"url": url})()
        self.response = response or _FakeResponse()
        self.outcome = None
        self.fetch_kwargs = None

    def abort(self):
        self.outcome = "abort"

    def continue_(self):
        self.outcome = "continue"

    def fetch(self, **kwargs):
        self.fetch_kwargs = kwargs
        return self.response

    def fulfill(self, response=None):
        self.outcome = "fulfill"


class RouteGuardTests(unittest.TestCase):
    def _guard(self, public_hosts: set):
        from urllib.parse import urlparse
        from ainews.video.screenshots import make_route_guard
        checked = []

        def check(url):
            checked.append(url)
            return urlparse(url).hostname in public_hosts

        return make_route_guard(check), checked

    def test_requests_to_private_hosts_are_aborted(self):
        guard, _ = self._guard({"news.example.com"})
        route = _FakeRoute("http://169.254.169.254/latest/meta-data/")
        guard(route)
        self.assertEqual(route.outcome, "abort")
        self.assertIsNone(route.fetch_kwargs)  # never fetched

    def test_requests_to_public_hosts_are_fetched_without_following_redirects(self):
        guard, _ = self._guard({"news.example.com"})
        route = _FakeRoute("https://news.example.com/story")
        guard(route)
        self.assertEqual(route.outcome, "fulfill")
        self.assertEqual(route.fetch_kwargs, {"max_redirects": 0})

    def test_redirect_to_a_private_host_is_aborted(self):
        guard, _ = self._guard({"news.example.com"})
        route = _FakeRoute("https://news.example.com/go", _FakeResponse(
            302, {"location": "http://169.254.169.254/latest/meta-data/"}))
        guard(route)
        self.assertEqual(route.outcome, "abort")

    def test_relative_redirect_on_a_public_host_is_allowed(self):
        guard, _ = self._guard({"news.example.com"})
        route = _FakeRoute("https://news.example.com/go", _FakeResponse(
            301, {"location": "/story"}))
        guard(route)
        self.assertEqual(route.outcome, "fulfill")

    def test_inline_data_urls_continue_without_a_lookup(self):
        guard, checked = self._guard(set())
        route = _FakeRoute("data:image/png;base64,AAAA")
        guard(route)
        self.assertEqual(route.outcome, "continue")
        self.assertEqual(checked, [])

    def test_host_decisions_are_cached_per_origin(self):
        guard, checked = self._guard({"cdn.example.com"})
        for path in ("a.js", "b.css", "c.png"):
            guard(_FakeRoute(f"https://cdn.example.com/{path}"))
        self.assertEqual(len(checked), 1)


class RouteGuardBrowserTests(unittest.TestCase):
    """Real Chromium: a redirect hop to a blocked host must never be requested.
    (Playwright route handlers don't see redirect hops the browser follows
    itself, which is why the guard fetches with max_redirects=0.)"""

    def test_redirect_into_a_blocked_host_is_not_followed(self):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from urllib.parse import urlparse

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest("playwright not installed")
        from ainews.video.screenshots import make_route_guard

        hits = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append((self.headers.get("Host", "").split(":")[0], self.path))
                if self.path == "/start":
                    self.send_response(302)
                    self.send_header("Location", f"http://localhost:{port}/secret")
                    self.end_headers()
                    return
                body = b"<h1>INTERNAL</h1>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        # In this test "127.0.0.1" plays the public site and "localhost" the
        # internal one; both resolve to this machine's test server.
        guard = make_route_guard(lambda url: urlparse(url).hostname == "127.0.0.1")
        try:
            with sync_playwright() as p:
                try:
                    # AINEWS_TEST_CHROMIUM: use an already-downloaded Chromium
                    # whose build doesn't match the installed Playwright.
                    executable = os.environ.get("AINEWS_TEST_CHROMIUM") or None
                    browser = p.chromium.launch(headless=True, executable_path=executable)
                except Exception as exc:  # browsers not installed here
                    self.skipTest(f"chromium unavailable: {exc}")
                context = browser.new_context(service_workers="block")
                context.route("**/*", guard)
                page = context.new_page()
                try:
                    page.goto(f"http://127.0.0.1:{port}/start", timeout=10000)
                except Exception:
                    pass  # aborted navigation is the expected outcome
                browser.close()
        finally:
            server.shutdown()

        self.assertIn(("127.0.0.1", "/start"), hits)
        self.assertNotIn("/secret", [path for _, path in hits])


if __name__ == "__main__":
    unittest.main()
