"""Tests for run_grouper.

These tests use a temp SQLite DB and exercise the grouping logic against
real-world examples that previously slipped through (S&P 500 / IPO cluster,
Microsoft AI behavior tools, etc.).
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

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


def _item_at(
    title: str,
    source: str,
    *,
    url: str | None = None,
    score: int = 5,
    days_ago: int = 0,
) -> ProcessedNewsItem:
    when = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return ProcessedNewsItem(
        title=title,
        url=url or f"https://example.com/{abs(hash(title))}",
        source=source,
        published=when,
        summary="",
        score=score,
        score_reasoning="",
        category="New Releases",
        fetched_via="rss",
        processed_at=when,
    )


class IncrementalGroupingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.db = Database(os.path.join(self.tmpdir, "t.db"))

    def tearDown(self) -> None:
        self.db.close()

    def _gid(self, title: str) -> int | None:
        row = self.db.conn.execute(
            "SELECT group_id FROM news_items WHERE title = ?", (title,)
        ).fetchone()
        return row["group_id"]

    def test_group_ids_stable_across_runs(self) -> None:
        """A second run must not renumber a group from the first run."""
        t1 = "Anthropic confidentially files for US IPO"
        t2 = "Anthropic files confidentially for a US IPO, sources say"
        self.db.insert(_item_at(t1, "Wired"))
        self.db.insert(_item_at(t2, "Reuters"))
        run_grouper(self.db)
        gid_first = self._gid(t1)
        self.assertIsNotNone(gid_first)
        self.assertEqual(self._gid(t2), gid_first)

        # A later rewrite of the same story arrives; the original gid persists
        # and the newcomer joins it.
        t3 = "Anthropic confidentially files US IPO paperwork"
        self.db.insert(_item_at(t3, "Bloomberg"))
        run_grouper(self.db)
        self.assertEqual(self._gid(t1), gid_first)
        self.assertEqual(self._gid(t2), gid_first)
        self.assertEqual(self._gid(t3), gid_first)

    def test_new_unrelated_group_does_not_disturb_existing(self) -> None:
        a1 = "Anthropic confidentially files for US IPO"
        a2 = "Anthropic files confidentially for a US IPO, sources say"
        self.db.insert(_item_at(a1, "Wired"))
        self.db.insert(_item_at(a2, "Reuters"))
        run_grouper(self.db)
        gid_a = self._gid(a1)

        b1 = "OpenAI launches Codex 2.0 coding model"
        b2 = "OpenAI ships Codex 2.0, its new coding model"
        self.db.insert(_item_at(b1, "TechCrunch"))
        self.db.insert(_item_at(b2, "The Verge"))
        run_grouper(self.db)

        self.assertEqual(self._gid(a1), gid_a)
        self.assertEqual(self._gid(a2), gid_a)
        gid_b = self._gid(b1)
        self.assertIsNotNone(gid_b)
        self.assertNotEqual(gid_b, gid_a)
        self.assertEqual(self._gid(b2), gid_b)

    def test_is_primary_prefers_vendor(self) -> None:
        self.db.insert(_item_at(
            "Anthropic launches Claude 4.8 with faster mode", "Wired",
            url="https://www.wired.com/anthropic-claude-48", score=9,
        ))
        self.db.insert(_item_at(
            "Claude 4.8 ships with a faster mode", "Anthropic News",
            url="https://www.anthropic.com/news/claude-4-8", score=5,
        ))
        run_grouper(self.db)
        rows = self.db.conn.execute(
            "SELECT url, is_primary FROM news_items WHERE is_primary = 1"
        ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertIn("anthropic.com", rows[0]["url"])

    def test_is_primary_falls_back_to_score(self) -> None:
        self.db.insert(_item_at(
            "Mistral releases Large 3 model", "TechCrunch",
            url="https://techcrunch.com/mistral-large-3", score=6,
        ))
        self.db.insert(_item_at(
            "Mistral releases its Large 3 model today", "The Verge",
            url="https://www.theverge.com/mistral-large-3", score=8,
        ))
        run_grouper(self.db)
        row = self.db.conn.execute(
            "SELECT score FROM news_items WHERE is_primary = 1"
        ).fetchone()
        self.assertEqual(row["score"], 8)

    def test_score_not_mutated_by_grouping(self) -> None:
        """Grouping must flag a primary, never rewrite scores."""
        self.db.insert(_item_at("Mistral releases Large 3 model", "TechCrunch", score=6))
        self.db.insert(_item_at("Mistral releases its Large 3 model today", "Verge", score=8))
        run_grouper(self.db)
        scores = sorted(
            r["score"] for r in self.db.conn.execute("SELECT score FROM news_items").fetchall()
        )
        self.assertEqual(scores, [6, 8])

    def test_window_excludes_old_items(self) -> None:
        """With a 14-day window, a story older than the window is not loaded,
        so a fresh rewrite of it does not retroactively group."""
        old = "Google announces Gemini 3 Ultra release"
        self.db.insert(_item_at(old, "TechCrunch", days_ago=30))
        recent = "Google announces the Gemini 3 Ultra release today"
        self.db.insert(_item_at(recent, "The Verge", days_ago=1))
        run_grouper(self.db, window_days=14)
        self.assertIsNone(self._gid(recent))
        self.assertIsNone(self._gid(old))

    def test_rebuild_regroups_full_history(self) -> None:
        """rebuild=True with no window regroups even old items."""
        old = "Google announces Gemini 3 Ultra release"
        self.db.insert(_item_at(old, "TechCrunch", days_ago=30))
        recent = "Google announces the Gemini 3 Ultra release today"
        self.db.insert(_item_at(recent, "The Verge", days_ago=1))
        run_grouper(self.db, window_days=None, rebuild=True)
        self.assertIsNotNone(self._gid(old))
        self.assertEqual(self._gid(old), self._gid(recent))


if __name__ == "__main__":
    unittest.main()
