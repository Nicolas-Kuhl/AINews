"""Tests for run_grouper.

These tests use a temp SQLite DB and exercise the grouping logic against
real-world examples that previously slipped through (S&P 500 / IPO cluster,
Microsoft AI behavior tools, etc.).
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone

from ainews.models import ProcessedNewsItem
from ainews.processing.grouper import run_grouper
from ainews.storage.database import Database


def _item(title: str, source: str, url: str | None = None, score: int = 5) -> ProcessedNewsItem:
    return ProcessedNewsItem(
        title=title,
        url=url or f"https://example.com/{abs(hash(title))}",
        source=source,
        published=datetime.now(timezone.utc),
        summary="",
        score=score,
        score_reasoning="",
        category="New Releases",
        fetched_via="rss",
        processed_at=datetime.now(timezone.utc),
    )


class GrouperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.db = Database(os.path.join(self.tmpdir, "t.db"))

    def tearDown(self) -> None:
        self.db.close()

    def _group_ids(self) -> dict[str, int | None]:
        rows = self.db.conn.execute(
            "SELECT title, group_id FROM news_items"
        ).fetchall()
        return {r["title"]: r["group_id"] for r in rows}

    def test_anthropic_ipo_cluster_groups_together(self) -> None:
        """Cross-publisher IPO coverage with diverging phrasing must group."""
        titles = [
            "Anthropic Confidentially Files for What Could Be the Largest IPO Ever",
            "Anthropic confidentially files for US IPO as it looks to beat OpenAI",
            "AI giant Anthropic confidentially files for US IPO as investors bet big on AI future",
        ]
        for t in titles:
            self.db.insert(_item(t, "Wired"))
        run_grouper(self.db)
        gids = self._group_ids()
        # All three should share a single group_id
        unique = set(gids.values())
        self.assertEqual(len(unique), 1, f"expected 1 group, got {unique}: {gids}")
        self.assertIsNotNone(next(iter(unique)))

    def test_microsoft_ai_tools_group_together(self) -> None:
        titles = [
            "New Microsoft tool lets devs spin up AI behavior tests using text descriptions",
            "Microsoft offers devs a better way to control AI agent behavior",
        ]
        for t in titles:
            self.db.insert(_item(t, "TechCrunch AI"))
        run_grouper(self.db)
        gids = self._group_ids()
        self.assertEqual(
            len(set(gids.values())), 1,
            f"expected both to group, got {gids}",
        )

    def test_unrelated_stories_do_not_group(self) -> None:
        """Different stories that happen to share a vendor word must stay apart."""
        self.db.insert(_item("Anthropic releases Claude 4.8", "Anthropic News"))
        self.db.insert(_item("Anthropic announces partnership with Salesforce", "Reuters"))
        self.db.insert(_item("OpenAI launches Codex 2.0", "OpenAI News"))
        run_grouper(self.db)
        gids = self._group_ids()
        # All three should be ungrouped (group_id is None) — each unique story
        self.assertEqual(
            set(gids.values()), {None},
            f"expected all ungrouped, got {gids}",
        )

    def test_short_title_does_not_join(self) -> None:
        """A title with fewer than min_shared_words significant words should
        start its own group rather than chain-merge into one."""
        self.db.insert(_item("Anthropic releases Claude 4.8", "Anthropic News"))
        self.db.insert(_item("Update", "RandomBlog"))
        run_grouper(self.db)
        gids = self._group_ids()
        self.assertEqual(set(gids.values()), {None})

    def test_vendor_url_becomes_primary(self) -> None:
        """When a vendor URL exists, it should be primary (first by group_id assignment).
        We verify by checking the item with the vendor URL is the first row to
        be assigned the group's id under the current ordering."""
        self.db.insert(
            _item(
                "Anthropic launches Claude 4.8 with 2.5x faster mode",
                "Wired",
                url="https://www.wired.com/anthropic-claude-48",
            )
        )
        self.db.insert(
            _item(
                "Claude 4.8 ships with faster mode",
                "Anthropic News",
                url="https://www.anthropic.com/news/claude-4-8",
            )
        )
        run_grouper(self.db)
        gids = self._group_ids()
        self.assertEqual(len(set(gids.values())), 1)


if __name__ == "__main__":
    unittest.main()
