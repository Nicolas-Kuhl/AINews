"""Smoke test for the fetch pipeline's main() — every stage stubbed out.

Exercises the full control flow end to end (including the run summary) so a
stale variable or a bad stage hand-off fails here instead of in cron.
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

import fetch_news
from ainews.models import ProcessedNewsItem, RawNewsItem


def _cfg(tmpdir: str) -> dict:
    return {
        "anthropic_api_key": "sk-test",
        "db_path": os.path.join(tmpdir, "ainews.db"),
        "rss_output_path": os.path.join(tmpdir, "high_priority.xml"),
        "model": "claude-test",
        "feeds": [{"name": "Feed", "url": "https://example.com/rss",
                   "type": "rss", "category": "trusted", "enabled": True}],
        "search_queries": [],
        "feed_timeout": 5,
        "max_items_per_feed": 5,
        "max_search_results": 5,
        "dedup_threshold": 80,
        "content_fetching": False,
        "embeddings": {"llm_dedup": False},
    }


def _raw() -> RawNewsItem:
    return RawNewsItem(
        title="Lab ships new model", url="https://example.com/a", source="Feed",
        published=datetime.now(timezone.utc), description="desc", fetched_via="rss",
    )


def _scored(items, *args, **kwargs):
    return [
        ProcessedNewsItem(
            title=i.title, url=i.url, source=i.source, published=i.published,
            summary="s", score=7, score_reasoning="r", category="New Releases",
            fetched_via=i.fetched_via,
        )
        for i in items
    ]


class FetchNewsMainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.cfg = _cfg(self.tmpdir)

    def _run_main(self, fetched: list[RawNewsItem]) -> None:
        with mock.patch.object(sys, "argv", ["fetch_news.py"]), \
             mock.patch.object(fetch_news, "load_config", return_value=self.cfg), \
             mock.patch.object(fetch_news, "setup_logging",
                               return_value=logging.getLogger("test_fetch_news")), \
             mock.patch.object(fetch_news, "fetch_all_feeds", return_value=fetched), \
             mock.patch.object(fetch_news, "search_all_queries", return_value=[]), \
             mock.patch.object(fetch_news, "score_items",
                               side_effect=lambda client, model, items, **kw: _scored(items)), \
             mock.patch("ainews.processing.clusterer.cluster_recent_items", return_value=0), \
             mock.patch("ainews.processing.brief.refresh_briefs", return_value={}):
            fetch_news.main()

    def test_run_with_new_items_completes_and_stamps_last_run(self) -> None:
        self._run_main([_raw()])
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, ".last_run")))

    def test_run_with_no_new_items_completes_and_stamps_last_run(self) -> None:
        self._run_main([])
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, ".last_run")))

    def test_fallback_scores_are_retried_even_when_nothing_new_arrives(self) -> None:
        with mock.patch.object(fetch_news, "rescore_fallback_items", return_value=0) as rescore:
            self._run_main([])
        rescore.assert_called_once()

    def test_fallback_scores_are_retried_on_runs_with_new_items(self) -> None:
        with mock.patch.object(fetch_news, "rescore_fallback_items", return_value=0) as rescore:
            self._run_main([_raw()])
        rescore.assert_called_once()

    def test_exits_without_fetching_while_another_run_holds_the_lock(self) -> None:
        from ainews.runlock import run_lock

        with run_lock(os.path.join(self.tmpdir, ".pipeline.lock")):
            with mock.patch.object(fetch_news, "get_due_feeds") as due:
                self._run_main([_raw()])
        due.assert_not_called()
        self.assertFalse(os.path.exists(os.path.join(self.tmpdir, ".last_run")))


if __name__ == "__main__":
    unittest.main()
