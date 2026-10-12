"""Tests for Claude scoring: fallback marking and rescoring of failed items."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from ainews.models import ProcessedNewsItem, RawNewsItem
from ainews.processing import scorer
from ainews.storage.database import Database


class _FakeMessages:
    def __init__(self, responder):
        self.responder = responder
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        return self.responder(kwargs)


def _client(responder):
    return SimpleNamespace(messages=_FakeMessages(responder))


def _json_reply(results: list[dict]):
    def responder(kwargs):
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(results))])
    return responder


def _failing(kwargs):
    raise RuntimeError("overloaded")


def _raw(n: int) -> RawNewsItem:
    return RawNewsItem(title=f"Story {n}", url=f"https://example.com/{n}", source="S",
                       description=f"desc {n}", fetched_via="rss")


def _good(n: int, score: int = 8) -> dict:
    return {"id": n, "short_summary": f"short {n}", "summary": f"long {n}", "score": score,
            "reasoning": "why", "learning_objectives": ["a"], "category": "Research"}


class ScoreBatchFallbackTests(unittest.TestCase):
    def test_api_error_items_are_marked_for_rescoring(self) -> None:
        out = scorer.score_items(_client(_failing), "m", [_raw(1), _raw(2)])
        self.assertEqual(len(out), 2)
        self.assertTrue(all(scorer.needs_rescore(i.score_reasoning) for i in out))

    def test_items_missing_from_the_response_are_marked_for_rescoring(self) -> None:
        out = scorer.score_items(_client(_json_reply([_good(1)])), "m", [_raw(1), _raw(2)])
        self.assertFalse(scorer.needs_rescore(out[0].score_reasoning))
        self.assertEqual(out[0].score, 8)
        self.assertTrue(scorer.needs_rescore(out[1].score_reasoning))

    def test_results_are_matched_by_id_not_position(self) -> None:
        # Model skipped item 1 and returned only item 2's result.
        out = scorer.score_items(_client(_json_reply([_good(2, 9)])), "m", [_raw(1), _raw(2)])
        self.assertTrue(scorer.needs_rescore(out[0].score_reasoning))
        self.assertEqual(out[1].score, 9)
        self.assertEqual(out[1].summary, "long 2")


    def test_batches_numbered_from_one_fall_back_to_position(self) -> None:
        # Model ignores the global [Item N] numbering and restarts at 1 each batch.
        client = _client(_json_reply([_good(1, 7), _good(2, 9)]))
        out = scorer.score_items(client, "m", [_raw(n) for n in range(1, 5)], batch_size=2)
        self.assertFalse(any(scorer.needs_rescore(i.score_reasoning) for i in out))
        self.assertEqual([i.score for i in out], [7, 9, 7, 9])


class RescoreFallbackItemsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = Database(os.path.join(tempfile.mkdtemp(), "t.db"))

    def tearDown(self) -> None:
        self.db.close()

    def _insert(self, n: int, reasoning: str, days_ago: float = 0) -> int:
        item = ProcessedNewsItem(
            title=f"Story {n}", url=f"https://example.com/{n}", source="S",
            summary=f"desc {n}", content=f"body {n}", score=5, score_reasoning=reasoning,
            category="Developer Tools", fetched_via="rss",
            processed_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        )
        return self.db.insert(item)

    def test_only_recent_fallback_rows_are_selected(self) -> None:
        fallback = self._insert(1, "Auto-scored (API error: overloaded)")
        self._insert(2, "Genuinely middling story")
        self._insert(3, "Auto-scored (API error: old)", days_ago=30)
        rows = self.db.get_items_needing_rescore(prefix=scorer.FALLBACK_REASON_PREFIX,
                                                 max_age_days=7, limit=50)
        self.assertEqual([r.id for r in rows], [fallback])

    def test_rescore_updates_score_and_drops_stale_embedding(self) -> None:
        item_id = self._insert(1, "Auto-scored (API error: overloaded)")
        self.db.upsert_embedding(item_id, "titan", 2, b"\x00" * 8)
        self.db.commit()

        n = scorer.rescore_fallback_items(self.db, _client(_json_reply([_good(1, 9)])), "m")

        self.assertEqual(n, 1)
        row = self.db.get_by_id(item_id)
        self.assertEqual(row.score, 9)
        self.assertEqual(row.summary, "long 1")
        self.assertEqual(row.short_summary, "short 1")
        self.assertEqual(row.category, "Research")
        self.assertFalse(scorer.needs_rescore(row.score_reasoning))
        self.assertEqual(self.db.get_embeddings([item_id], "titan"), {})

    def test_failed_rescore_backs_off_exponentially(self) -> None:
        item_id = self._insert(1, "Auto-scored (API error: overloaded)")
        client = _client(_failing)
        now = datetime.now(timezone.utc)

        def due(at):
            return [r.id for r in self.db.get_items_needing_rescore(
                prefix=scorer.FALLBACK_REASON_PREFIX, max_age_days=7, limit=50, now=at)]

        scorer.rescore_fallback_items(self.db, client, "m", now=now)
        self.assertEqual(client.messages.calls, 1)
        self.assertEqual(due(now + timedelta(minutes=10)), [])        # deferred 15 min
        self.assertEqual(due(now + timedelta(minutes=16)), [item_id])

        scorer.rescore_fallback_items(self.db, client, "m", now=now + timedelta(minutes=16))
        self.assertEqual(due(now + timedelta(minutes=16 + 25)), [])   # deferred 30 min
        self.assertEqual(due(now + timedelta(minutes=16 + 31)), [item_id])

    def test_still_failing_rows_stay_marked(self) -> None:
        item_id = self._insert(1, "Auto-scored (API error: overloaded)")
        n = scorer.rescore_fallback_items(self.db, _client(_failing), "m")
        self.assertEqual(n, 0)
        self.assertTrue(scorer.needs_rescore(self.db.get_by_id(item_id).score_reasoning))


if __name__ == "__main__":
    unittest.main()
