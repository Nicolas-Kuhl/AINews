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

    def _run_main(self, fetched: list[RawNewsItem], argv: tuple = ()) -> None:
        with mock.patch.object(sys, "argv", ["fetch_news.py", *argv]), \
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

    def test_pipeline_runs_under_a_watchdog_that_is_cancelled_afterwards(self) -> None:
        with mock.patch.object(fetch_news, "start_watchdog") as dog:
            self._run_main([_raw()])
        dog.assert_called_once()
        self.assertEqual(dog.call_args.args[0], fetch_news.MAX_RUN_SECONDS)
        dog.return_value.cancel.assert_called_once()

    def test_open_run_outwaits_a_hung_run_killed_by_its_watchdog(self) -> None:
        # Otherwise a hung trusted run at 18:00 would also cost the open run.
        self.assertGreater(fetch_news.LOCK_WAIT_SECONDS, fetch_news.MAX_RUN_SECONDS)

    def test_trusted_run_skips_while_another_run_holds_the_lock(self) -> None:
        from ainews.runlock import run_lock

        with run_lock(os.path.join(self.tmpdir, ".pipeline.lock")):
            with mock.patch.object(fetch_news, "get_due_feeds") as due:
                with self.assertRaises(SystemExit) as exit_:
                    self._run_main([_raw()], argv=("--category", "trusted"))
        due.assert_not_called()
        self.assertNotEqual(exit_.exception.code, 0)
        self.assertFalse(os.path.exists(os.path.join(self.tmpdir, ".last_run")))

    def test_open_run_waits_for_the_lock_instead_of_skipping(self) -> None:
        """The */15 trusted cron and the daily open cron both fire at 18:00;
        the open run (open feeds, search, newsletters) must not be dropped."""
        import threading
        import time
        from ainews.runlock import run_lock

        held = threading.Event()

        def trusted_run_in_progress():
            with run_lock(os.path.join(self.tmpdir, ".pipeline.lock")):
                held.set()
                time.sleep(0.5)

        t = threading.Thread(target=trusted_run_in_progress)
        t.start()
        held.wait(2)
        with mock.patch.object(fetch_news, "LOCK_POLL_SECONDS", 0.05):
            self._run_main([_raw()], argv=("--category", "open"))
        t.join()
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, ".last_run")))

    def test_no_wait_flag_returns_immediately_with_the_locked_exit_code(self) -> None:
        """For the dashboard's Run button: report 'already running' at once
        instead of blocking the page for up to the full wait limit."""
        import time
        from ainews.runlock import run_lock

        with run_lock(os.path.join(self.tmpdir, ".pipeline.lock")), \
             mock.patch.object(fetch_news, "LOCK_WAIT_SECONDS", 30):
            start = time.monotonic()
            with self.assertRaises(SystemExit) as exit_:
                self._run_main([_raw()], argv=("--no-wait",))
        self.assertLess(time.monotonic() - start, 2)
        self.assertEqual(exit_.exception.code, fetch_news.EXIT_LOCKED)

    def test_open_run_gives_up_after_the_wait_limit(self) -> None:
        from ainews.runlock import run_lock

        with run_lock(os.path.join(self.tmpdir, ".pipeline.lock")), \
             mock.patch.object(fetch_news, "LOCK_WAIT_SECONDS", 0.2), \
             mock.patch.object(fetch_news, "LOCK_POLL_SECONDS", 0.05):
            with self.assertRaises(SystemExit) as exit_:
                self._run_main([_raw()], argv=("--category", "open"))
        self.assertNotEqual(exit_.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
