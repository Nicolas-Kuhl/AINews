"""Undated items must not appear in the chronological digest (query_by_day)."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone

from ainews.models import ProcessedNewsItem
from ainews.storage.database import Database


def _item(title, published):
    return ProcessedNewsItem(
        title=title, url=f"https://example.com/{abs(hash(title))}", source="Src",
        published=published, summary="", short_summary="", score=7,
        score_reasoning="", category="New Releases", fetched_via="html_scrape",
        processed_at=datetime.now(timezone.utc),
    )


class DigestUndatedTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(os.path.join(tempfile.mkdtemp(), "t.db"))

    def tearDown(self):
        self.db.close()

    def test_undated_items_excluded_from_day_view(self):
        self.db.insert(_item("Real story", datetime.now(timezone.utc)))
        self.db.insert(_item("Folder: Models", None))     # nav junk, no date
        self.db.insert(_item("Skip to main content", None))

        by_day = self.db.query_by_day(min_score=1, show_acknowledged=True, limit_days=30)

        all_titles = [p.title for groups in by_day.values() for p, _ in groups]
        self.assertIn("Real story", all_titles)
        self.assertNotIn("Folder: Models", all_titles)
        self.assertNotIn("Skip to main content", all_titles)
        self.assertNotIn("Unknown", by_day)  # no Unknown bucket at all


if __name__ == "__main__":
    unittest.main()
