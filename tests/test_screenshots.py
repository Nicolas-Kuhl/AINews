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


if __name__ == "__main__":
    unittest.main()
