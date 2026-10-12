"""Tests for the pure logic of segment-backdrop screenshots (no Playwright/PIL)."""

from __future__ import annotations

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




class _FakeRoute:
    def __init__(self, url: str):
        self.request = type("Req", (), {"url": url})()
        self.outcome = None

    def abort(self):
        self.outcome = "abort"

    def continue_(self):
        self.outcome = "continue"


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

    def test_requests_to_public_hosts_continue(self):
        guard, _ = self._guard({"news.example.com"})
        route = _FakeRoute("https://news.example.com/story")
        guard(route)
        self.assertEqual(route.outcome, "continue")

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


if __name__ == "__main__":
    unittest.main()
