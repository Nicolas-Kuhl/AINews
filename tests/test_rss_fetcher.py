"""Tests for concurrent feed fetching in fetch_all_feeds.

The per-feed fetch is monkeypatched so these run without network access.
"""

from __future__ import annotations

import time
import unittest

from ainews.fetchers import rss_fetcher
from ainews.models import RawNewsItem


def _raw(title: str) -> RawNewsItem:
    return RawNewsItem(title=title, url=f"https://x/{title}", source="s", fetched_via="rss")


class FetchAllFeedsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig = rss_fetcher._fetch_one_feed

    def tearDown(self) -> None:
        rss_fetcher._fetch_one_feed = self._orig

    def test_aggregates_results_from_all_feeds(self) -> None:
        def fake(fc, timeout, max_items):
            return [_raw(fc["name"])]

        rss_fetcher._fetch_one_feed = fake
        feeds = [{"name": f"f{i}", "type": "rss"} for i in range(5)]
        items = rss_fetcher.fetch_all_feeds(feeds, timeout=5)
        self.assertEqual(sorted(i.title for i in items), ["f0", "f1", "f2", "f3", "f4"])

    def test_one_failing_feed_does_not_abort_batch(self) -> None:
        def fake(fc, timeout, max_items):
            if fc["name"] == "bad":
                raise RuntimeError("boom")
            return [_raw(fc["name"])]

        rss_fetcher._fetch_one_feed = fake
        feeds = [{"name": "ok1", "type": "rss"}, {"name": "bad", "type": "rss"},
                 {"name": "ok2", "type": "rss"}]
        items = rss_fetcher.fetch_all_feeds(feeds, timeout=5)
        self.assertEqual(sorted(i.title for i in items), ["ok1", "ok2"])

    def test_disabled_feeds_skipped(self) -> None:
        def fake(fc, timeout, max_items):
            return [_raw(fc["name"])]

        rss_fetcher._fetch_one_feed = fake
        feeds = [{"name": "on", "type": "rss"}, {"name": "off", "type": "rss", "enabled": False}]
        items = rss_fetcher.fetch_all_feeds(feeds, timeout=5)
        self.assertEqual([i.title for i in items], ["on"])

    def test_slow_feed_runs_concurrently_with_fast_ones(self) -> None:
        """Ten 0.2s feeds should finish in well under the 2s serial total."""
        def fake(fc, timeout, max_items):
            time.sleep(0.2)
            return [_raw(fc["name"])]

        rss_fetcher._fetch_one_feed = fake
        feeds = [{"name": f"f{i}", "type": "rss"} for i in range(10)]
        start = time.monotonic()
        items = rss_fetcher.fetch_all_feeds(feeds, timeout=5, max_workers=10)
        elapsed = time.monotonic() - start
        self.assertEqual(len(items), 10)
        self.assertLess(elapsed, 1.0)  # serial would be ~2.0s

    def test_global_deadline_returns_without_waiting_for_hung_feed(self) -> None:
        def fake(fc, timeout, max_items):
            if fc["name"] == "hung":
                time.sleep(3)
            return [_raw(fc["name"])]

        rss_fetcher._fetch_one_feed = fake
        feeds = [{"name": "fast", "type": "rss"}, {"name": "hung", "type": "rss"}]
        start = time.monotonic()
        items = rss_fetcher.fetch_all_feeds(feeds, timeout=5, total_timeout=0.5)
        elapsed = time.monotonic() - start
        self.assertEqual([i.title for i in items], ["fast"])
        self.assertLess(elapsed, 1.5)  # must not block on the hung feed's 3s


_RSS_BODY = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>T</title>
<item><title>Model launch</title><link>https://example.com/a</link>
<pubDate>Mon, 12 Oct 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""


class _FakeResponse:
    def __init__(self, content: bytes):
        self.content = content
        self.text = content.decode()
        self.headers = {"content-type": "application/rss+xml"}


class FetchRssDirectTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig = rss_fetcher._fetch_with_retry

    def tearDown(self) -> None:
        rss_fetcher._fetch_with_retry = self._orig

    def test_rss_feed_is_fetched_with_the_configured_timeout(self) -> None:
        calls = []

        def fake_get(url, timeout, headers):
            calls.append((url, timeout))
            return _FakeResponse(_RSS_BODY)

        rss_fetcher._fetch_with_retry = fake_get
        items = rss_fetcher._fetch_rss_direct(
            {"name": "Feed", "url": "https://feeds.invalid/rss"}, timeout=7, max_items=10
        )
        self.assertEqual(calls, [("https://feeds.invalid/rss", 7)])
        self.assertEqual([i.title for i in items], ["Model launch"])


if __name__ == "__main__":
    unittest.main()
