"""Tests for cron dueness checks in fetch_news.

Reproduces the production skew bug: a feed scanned seconds AFTER the cron
tick (because fetching takes time) was one second "not due" at the next
tick, silently skipping daily feeds every other day.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta

from ainews.storage.database import Database
from fetch_news import _due_grace_minutes, get_due_feeds, get_due_queries


class DueGraceTests(unittest.TestCase):
    def test_floor_of_two_minutes_for_short_intervals(self):
        self.assertEqual(_due_grace_minutes(15), 2.0)

    def test_one_percent_for_long_intervals(self):
        self.assertAlmostEqual(_due_grace_minutes(1440), 14.4)


class GetDueFeedsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.db = Database(os.path.join(self.tmpdir, "t.db"))
        self.cfg = {"trusted_interval": 15, "open_interval": 1440}

    def tearDown(self) -> None:
        self.db.close()

    def _feed(self, name: str, category: str) -> dict:
        return {"name": name, "url": "https://example.com/feed", "category": category}

    def _scanned_minutes_ago(self, name: str, minutes: float) -> None:
        ts = (datetime.now() - timedelta(minutes=minutes)).isoformat()
        self.db.update_feed_last_scanned(name, ts)

    def test_never_scanned_feed_is_due(self):
        feeds = [self._feed("Fresh", "open")]
        self.assertEqual(len(get_due_feeds(feeds, self.cfg, self.db)), 1)

    def test_daily_feed_scanned_just_under_interval_is_due(self):
        """The production bug: stamped at 18:00:03, checked at next 18:00:02."""
        self._scanned_minutes_ago("TechCrunch AI", 1440 - (1 / 60))
        feeds = [self._feed("TechCrunch AI", "open")]
        self.assertEqual(len(get_due_feeds(feeds, self.cfg, self.db)), 1)

    def test_daily_feed_scanned_an_hour_ago_is_not_due(self):
        self._scanned_minutes_ago("TechCrunch AI", 60)
        feeds = [self._feed("TechCrunch AI", "open")]
        self.assertEqual(get_due_feeds(feeds, self.cfg, self.db), [])

    def test_daily_feed_well_inside_grace_window_is_not_due(self):
        # 23 hours elapsed: inside the interval minus grace, must not run early.
        self._scanned_minutes_ago("TechCrunch AI", 1380)
        feeds = [self._feed("TechCrunch AI", "open")]
        self.assertEqual(get_due_feeds(feeds, self.cfg, self.db), [])

    def test_trusted_feed_skew_is_tolerated(self):
        self._scanned_minutes_ago("OpenAI News", 14.5)
        feeds = [self._feed("OpenAI News", "trusted")]
        self.assertEqual(len(get_due_feeds(feeds, self.cfg, self.db)), 1)

    def test_disabled_feed_never_due(self):
        feeds = [{**self._feed("Off", "open"), "enabled": False}]
        self.assertEqual(get_due_feeds(feeds, self.cfg, self.db), [])

    def test_queries_use_same_grace(self):
        ts = (datetime.now() - timedelta(minutes=1440 - 0.05)).isoformat()
        self.db.update_feed_last_scanned("search:ai news", ts)
        queries = [{"query": "ai news", "category": "open"}]
        self.assertEqual(len(get_due_queries(queries, self.cfg, self.db)), 1)


if __name__ == "__main__":
    unittest.main()
