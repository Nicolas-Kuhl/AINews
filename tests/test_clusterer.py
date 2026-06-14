"""Tests for the embedding-based story clusterer.

Uses a fake embedder with hand-placed vectors — no Bedrock, no network. The
geometry is the point: same-story items get near-identical vectors, same-topic
items get moderately-similar ones, and the tests assert the clusterer keeps
those regimes apart (the lexical grouper's failure mode).
"""

from __future__ import annotations

import math
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from ainews.models import ProcessedNewsItem
from ainews.processing.clusterer import cluster_recent_items
from ainews.processing.embeddings import (
    cosine,
    item_embed_text,
    mean_vector,
    pack_vector,
    unpack_vector,
)
from ainews.storage.database import Database


def _unit(angle: float) -> list[float]:
    """2-D unit vector at the given angle (radians) — geometry made obvious."""
    return [math.cos(angle), math.sin(angle)]


class _FakeEmbedder:
    """Maps exact titles to fixed vectors."""

    model_id = "fake-test-model"

    def __init__(self, mapping: dict[str, list[float]]):
        self.mapping = mapping
        self.embed_calls = 0

    def embed(self, text: str) -> list[float]:
        self.embed_calls += 1
        title = text.split("\n")[0]
        return self.mapping[title]


def _item(title: str, days_ago: float = 0, score: int = 7) -> ProcessedNewsItem:
    return ProcessedNewsItem(
        title=title,
        url=f"https://example.com/{abs(hash(title))}",
        source="Src",
        published=datetime.now(timezone.utc) - timedelta(days=days_ago),
        summary=f"About {title}",
        short_summary=f"Short about {title}",
        score=score,
        score_reasoning="",
        category="New Releases",
        fetched_via="rss",
        processed_at=datetime.now(timezone.utc),
    )


class VectorUtilTests(unittest.TestCase):
    def test_pack_unpack_roundtrip(self):
        v = [0.25, -1.5, 3.0]
        out = unpack_vector(pack_vector(v))
        for a, b in zip(v, out):
            self.assertAlmostEqual(a, b, places=6)

    def test_cosine_and_centroid(self):
        self.assertAlmostEqual(cosine(_unit(0), _unit(0)), 1.0, places=6)
        self.assertAlmostEqual(cosine(_unit(0), _unit(math.pi / 2)), 0.0, places=6)
        c = mean_vector([_unit(0), _unit(math.pi / 2)])
        self.assertAlmostEqual(c[0], 0.5, places=6)

    def test_embed_text_prefers_short_summary(self):
        self.assertEqual(item_embed_text("T", "short", "long"), "T\nshort")
        self.assertEqual(item_embed_text("T", "", "long"), "T\nlong")
        self.assertEqual(item_embed_text("T", None, None), "T")


class ClustererTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db = Database(os.path.join(self.tmpdir, "t.db"))

    def tearDown(self):
        self.db.close()

    def _insert(self, items):
        for it in items:
            self.db.insert(it)

    def _groups(self) -> dict[str, int]:
        rows = self.db.conn.execute(
            "SELECT title, group_id FROM news_items").fetchall()
        return {r["title"]: r["group_id"] for r in rows}

    def test_same_story_clusters_different_topics_stay_apart(self):
        # Release coverage: three outlets, nearly identical vectors.
        # IPO story: same entity (would share words!), distant vector.
        mapping = {
            "Anthropic releases Fable 5": _unit(0.00),
            "Guardrailed Mythos goes public": _unit(0.05),
            "Fable 5 is Mythos for everyone": _unit(0.08),
            "Anthropic files for IPO": _unit(1.0),  # ~0.54 cosine from release
        }
        self._insert([_item(t) for t in mapping])

        cluster_recent_items(self.db, _FakeEmbedder(mapping), threshold=0.8)

        g = self._groups()
        release_gids = {g["Anthropic releases Fable 5"],
                        g["Guardrailed Mythos goes public"],
                        g["Fable 5 is Mythos for everyone"]}
        self.assertEqual(len(release_gids), 1)
        self.assertIsNotNone(release_gids.pop())
        self.assertIsNone(g["Anthropic files for IPO"])  # singleton, no gid

    def test_centroid_assignment_prevents_chaining(self):
        # A and B are similar; C is similar to B but NOT to the A+B centroid.
        # Single-link would chain C in via B; centroid must refuse.
        mapping = {
            "Story A": _unit(0.00),
            "Story B": _unit(0.55),   # cos(0.55) ≈ 0.85 → joins A
            "Story C": _unit(1.10),   # cos to B ≈ 0.85, cos to centroid(A,B) ≈ 0.72
        }
        self._insert([_item("Story A", days_ago=2),
                      _item("Story B", days_ago=1),
                      _item("Story C", days_ago=0)])

        cluster_recent_items(self.db, _FakeEmbedder(mapping), threshold=0.8)

        g = self._groups()
        self.assertIsNotNone(g["Story A"])
        self.assertEqual(g["Story A"], g["Story B"])
        self.assertNotEqual(g["Story C"], g["Story A"])  # chain broken

    def test_time_span_cap_blocks_old_cluster_growth(self):
        # Identical vectors but 10 days apart — same topic resurfacing is a
        # NEW story, not a 10-day-old cluster's member.
        mapping = {
            "Mythos news week one": _unit(0.0),
            "Mythos news week two": _unit(0.01),
            "Mythos news much later": _unit(0.02),
        }
        self._insert([_item("Mythos news week one", days_ago=10),
                      _item("Mythos news week two", days_ago=9.5),
                      _item("Mythos news much later", days_ago=0)])

        cluster_recent_items(
            self.db, _FakeEmbedder(mapping), threshold=0.8, max_span_days=4,
        )

        g = self._groups()
        self.assertEqual(g["Mythos news week one"], g["Mythos news week two"])
        self.assertNotEqual(g["Mythos news much later"], g["Mythos news week one"])

    def test_incremental_runs_are_stable_and_cached(self):
        mapping = {
            "Alpha launch": _unit(0.0),
            "Alpha launch covered again": _unit(0.04),
            "Beta funding round": _unit(1.2),
        }
        self._insert([_item(t) for t in mapping])
        embedder = _FakeEmbedder(mapping)

        cluster_recent_items(self.db, embedder, threshold=0.8)
        first = self._groups()
        calls_after_first = embedder.embed_calls

        cluster_recent_items(self.db, embedder, threshold=0.8)
        second = self._groups()

        self.assertEqual(first, second)              # ids stable
        self.assertEqual(embedder.embed_calls, calls_after_first)  # vectors cached

    def test_new_item_joins_existing_cluster_and_primary_recomputed(self):
        mapping = {
            "Launch day report": _unit(0.0),
            "Launch day, other outlet": _unit(0.03),
            "Launch followup": _unit(0.05),
        }
        self._insert([_item("Launch day report", days_ago=1, score=8),
                      _item("Launch day, other outlet", days_ago=1, score=6)])
        embedder = _FakeEmbedder(mapping)
        cluster_recent_items(self.db, embedder, threshold=0.8)

        self._insert([_item("Launch followup", days_ago=0, score=9)])
        cluster_recent_items(self.db, embedder, threshold=0.8)

        g = self._groups()
        self.assertEqual(len({g[t] for t in mapping}), 1)
        prim = self.db.conn.execute(
            "SELECT COUNT(*) FROM news_items WHERE is_primary = 1").fetchone()[0]
        self.assertEqual(prim, 1)

    def test_rebuild_renumbers_from_scratch(self):
        mapping = {"One": _unit(0.0), "Two": _unit(0.02)}
        self._insert([_item(t) for t in mapping])
        embedder = _FakeEmbedder(mapping)
        cluster_recent_items(self.db, embedder, threshold=0.8)

        touched = cluster_recent_items(
            self.db, embedder, threshold=0.8, rebuild=True,
        )

        g = self._groups()
        self.assertEqual(g["One"], g["Two"])
        self.assertIsNotNone(g["One"])
        self.assertEqual(touched, 1)


if __name__ == "__main__":
    unittest.main()


class BorderlineJudgeTests(unittest.TestCase):
    """Stage-2 LLM-judged merges for pairs in the borderline cosine band."""

    def setUp(self):
        import tempfile, os
        self.db = Database(os.path.join(tempfile.mkdtemp(), "t.db"))

    def tearDown(self):
        self.db.close()

    def _groups(self):
        rows = self.db.conn.execute("SELECT title, group_id FROM news_items").fetchall()
        return {r["title"]: r["group_id"] for r in rows}

    def test_borderline_same_event_merges_when_judge_says_yes(self):
        # Two items ~0.62 apart (borderline: below 0.80 auto, above 0.45 floor).
        mapping = {
            "Anthropic suspends Mythos access": _unit(0.0),
            "Europe reacts to Anthropic halting Mythos": _unit(0.9),  # cos≈0.62
        }
        for t in mapping:
            self._insert(self.db, t, mapping)
        judged = []
        def judge(pairs):
            judged.append(pairs)
            return [True] * len(pairs)  # "same event"
        cluster_recent_items(self.db, _FakeEmbedder(mapping), threshold=0.80, judge=judge)
        g = self._groups()
        self.assertEqual(len(judged), 1)  # judge was consulted
        self.assertEqual(g["Anthropic suspends Mythos access"],
                         g["Europe reacts to Anthropic halting Mythos"])
        self.assertIsNotNone(g["Anthropic suspends Mythos access"])

    def test_borderline_different_event_stays_split_when_judge_says_no(self):
        mapping = {
            "OpenAI threat report on Chinese actors": _unit(0.0),
            "Google sues Chinese cybercrime network": _unit(0.9),  # cos≈0.62, same topic
        }
        for t in mapping:
            self._insert(self.db, t, mapping)
        cluster_recent_items(self.db, _FakeEmbedder(mapping), threshold=0.80,
                             judge=lambda pairs: [False] * len(pairs))
        g = self._groups()
        self.assertIsNone(g["OpenAI threat report on Chinese actors"])
        self.assertIsNone(g["Google sues Chinese cybercrime network"])

    def test_below_floor_never_reaches_judge(self):
        mapping = {
            "Totally unrelated story A": _unit(0.0),
            "Totally unrelated story B": _unit(1.2),  # cos≈0.36 < 0.45 floor
        }
        for t in mapping:
            self._insert(self.db, t, mapping)
        seen = []
        cluster_recent_items(self.db, _FakeEmbedder(mapping), threshold=0.80,
                             judge=lambda pairs: seen.append(pairs) or [True] * len(pairs))
        # No pair entered the band, so judge got nothing (or wasn't asked to merge)
        self.assertTrue(all(len(p) == 0 for p in seen) or not seen)
        g = self._groups()
        self.assertIsNone(g["Totally unrelated story A"])

    def _insert(self, db, title, mapping):
        from datetime import datetime, timezone
        it = _item(title, score=7)
        it.published = datetime.now(timezone.utc)
        db.insert(it)
