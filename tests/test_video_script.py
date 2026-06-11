"""Tests for the video script generator (Stage 1 of the video pipeline).

Uses a temp SQLite DB for story selection and a stub Anthropic client for
script generation, so no network or API key is needed.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ainews.models import ProcessedNewsItem
from ainews.processing.video_script import (
    count_narration_words,
    generate_script,
    run_video_script,
    select_stories,
    write_script_files,
)
from ainews.storage.database import Database


def _item(
    title: str,
    score: int = 7,
    hours_ago: int = 2,
    source: str = "OpenAI News",
) -> ProcessedNewsItem:
    return ProcessedNewsItem(
        title=title,
        url=f"https://example.com/{abs(hash(title))}",
        source=source,
        published=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
        summary=f"Summary of {title}. It matters because reasons.",
        score=score,
        score_reasoning="",
        category="New Releases",
        fetched_via="rss",
        processed_at=datetime.now(timezone.utc),
    )


def _script_response(n_segments: int, words_per_section: int = 100) -> dict:
    """Build a structurally valid script with a controllable word count."""
    narration = " ".join(["word"] * words_per_section)
    return {
        "title": "Robots Did Things Again",
        "cold_open": narration,
        "segments": [
            {
                "slug": f"story-{i}",
                "headline": f"Headline {i}",
                "source": "OpenAI News",
                "url": f"https://example.com/{i}",
                "narration": narration,
                "bullets": [
                    {"text": f"Fact {j}", "anchor": "word word"}
                    for j in range(3)
                ],
            }
            for i in range(n_segments)
        ],
        "sign_off": narration,
    }


class _StubMessages:
    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)

        class _Block:
            def __init__(self, text):
                self.text = text

        class _Response:
            def __init__(self, text):
                self.content = [_Block(text)]

        return _Response(self._responses.pop(0))


class _StubClient:
    """Stands in for anthropic.Anthropic; returns canned response texts."""

    def __init__(self, responses: list[str]):
        self.messages = _StubMessages(responses)


class SelectStoriesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.db = Database(os.path.join(self.tmpdir, "t.db"))

    def tearDown(self) -> None:
        self.db.close()

    def test_filters_by_score_window_and_limit(self) -> None:
        self.db.insert(_item("Big story", score=9))
        self.db.insert(_item("Decent story", score=6))
        self.db.insert(_item("Too weak", score=4))
        self.db.insert(_item("Too old", score=10, hours_ago=72))
        for i in range(8):
            self.db.insert(_item(f"Filler {i}", score=6))

        stories = select_stories(self.db, hours=24, min_score=6, max_stories=5)

        self.assertEqual(len(stories), 5)
        titles = [p.title for p, _ in stories]
        self.assertEqual(titles[0], "Big story")
        self.assertNotIn("Too weak", titles)
        self.assertNotIn("Too old", titles)

    def test_grouped_stories_collapse_to_primary(self) -> None:
        a = self.db.insert(_item("Anthropic files IPO", score=9))
        b = self.db.insert(_item("Anthropic IPO filing confirmed", score=7, source="Wired"))
        self.db.set_group(a, 1)
        self.db.set_group(b, 1)

        stories = select_stories(self.db, hours=24, min_score=6, max_stories=5)

        self.assertEqual(len(stories), 1)
        primary, related = stories[0]
        self.assertEqual(primary.title, "Anthropic files IPO")
        self.assertEqual([r.title for r in related], ["Anthropic IPO filing confirmed"])

    def test_acknowledged_items_still_selected(self) -> None:
        item_id = self.db.insert(_item("Already triaged", score=8))
        self.db.acknowledge(item_id)

        stories = select_stories(self.db, hours=24, min_score=6, max_stories=5)

        self.assertEqual([p.title for p, _ in stories], ["Already triaged"])


class GenerateScriptTests(unittest.TestCase):
    def _stories(self, n: int = 3):
        return [(_item(f"Story {i}", score=8), []) for i in range(n)]

    def test_accepts_in_band_draft_without_revision(self) -> None:
        # 5 sections x 155 words = 775 = exactly on target for 5 min @ 155wpm
        draft = _script_response(3, words_per_section=155)
        client = _StubClient([json.dumps(draft)])

        script = generate_script(client, self._stories(3), target_minutes=5)

        self.assertEqual(len(client.messages.calls), 1)
        self.assertEqual(script["meta"]["narration_words"], 775)
        self.assertEqual(script["meta"]["story_count"], 3)

    def test_short_draft_triggers_one_revision(self) -> None:
        short = _script_response(3, words_per_section=50)   # 250 words
        fixed = _script_response(3, words_per_section=155)  # 775 words
        client = _StubClient([json.dumps(short), json.dumps(fixed)])

        script = generate_script(client, self._stories(3), target_minutes=5)

        self.assertEqual(len(client.messages.calls), 2)
        self.assertEqual(script["meta"]["narration_words"], 775)
        # Revision call must carry the conversation (draft + correction)
        self.assertEqual(len(client.messages.calls[1]["messages"]), 3)

    def test_invalid_revision_keeps_first_draft(self) -> None:
        long_draft = _script_response(3, words_per_section=300)
        broken = {"title": "oops"}  # structurally invalid revision
        client = _StubClient([json.dumps(long_draft), json.dumps(broken)])

        script = generate_script(client, self._stories(3), target_minutes=5)

        self.assertEqual(len(script["segments"]), 3)

    def test_parses_fenced_json(self) -> None:
        draft = _script_response(2, words_per_section=194)
        fenced = "```json\n" + json.dumps(draft) + "\n```"
        client = _StubClient([fenced])

        script = generate_script(client, self._stories(2), target_minutes=5)

        self.assertEqual(script["title"], "Robots Did Things Again")

    def test_wrong_segment_count_raises(self) -> None:
        draft = _script_response(2, words_per_section=155)  # 2 segments for 3 stories
        client = _StubClient([json.dumps(draft)])

        with self.assertRaises(ValueError):
            generate_script(client, self._stories(3), target_minutes=5)

    def test_empty_stories_raises(self) -> None:
        with self.assertRaises(ValueError):
            generate_script(_StubClient([]), [], target_minutes=5)


class WordCountTests(unittest.TestCase):
    def test_counts_all_narration_sections(self) -> None:
        script = _script_response(4, words_per_section=10)
        self.assertEqual(count_narration_words(script), 60)

    def test_tolerates_missing_fields(self) -> None:
        self.assertEqual(count_narration_words({}), 0)


class OutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp())

    def test_writes_json_and_markdown(self) -> None:
        script = _script_response(2, words_per_section=20)
        script["meta"] = {"narration_words": 80, "estimated_runtime_seconds": 31}

        json_path, md_path = write_script_files(script, self.tmpdir, "2026-06-10")

        with open(json_path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["title"], "Robots Did Things Again")
        md = md_path.read_text(encoding="utf-8")
        self.assertIn("# Robots Did Things Again", md)
        self.assertIn("## Segment 2: Headline 1", md)
        self.assertIn("## Sign-off", md)

    def test_run_end_to_end_with_db(self) -> None:
        db = Database(str(self.tmpdir / "t.db"))
        try:
            db.insert(_item("Big story", score=9))
            db.insert(_item("Other story", score=7))
            draft = _script_response(2, words_per_section=194)
            client = _StubClient([json.dumps(draft)])

            result = run_video_script(
                db, client, output_dir=self.tmpdir / "scripts",
                min_score=6, max_stories=5, target_minutes=5,
            )

            self.assertEqual(result["status"], "ok")
            self.assertTrue(Path(result["json_path"]).exists())
            self.assertTrue(Path(result["md_path"]).exists())
            self.assertEqual(result["story_count"], 2)
        finally:
            db.close()

    def test_run_with_empty_db_skips(self) -> None:
        db = Database(str(self.tmpdir / "t.db"))
        try:
            result = run_video_script(
                db, _StubClient([]), output_dir=self.tmpdir / "scripts",
            )
            self.assertEqual(result["status"], "no-stories")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()


class StorySelectionWindowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.db = Database(os.path.join(self.tmpdir, "t.db"))

    def tearDown(self) -> None:
        self.db.close()

    def test_exclude_urls_drops_covered_stories(self):
        self.db.insert(_item("Covered story", score=9))
        self.db.insert(_item("Fresh story", score=8))
        covered = [i for i in self.db.query_items(limit=10) if i.title == "Covered story"]

        stories = select_stories(
            self.db, hours=72, min_score=6, max_stories=5,
            exclude_urls={covered[0].url},
        )

        self.assertEqual([p.title for p, _ in stories], ["Fresh story"])

    def test_wide_lookback_catches_older_big_story(self):
        self.db.insert(_item("Two days ago banger", score=9, hours_ago=50))
        self.db.insert(_item("Today's medium story", score=6, hours_ago=2))

        stories = select_stories(self.db, hours=72, min_score=6, max_stories=5)

        self.assertEqual(stories[0][0].title, "Two days ago banger")

    def test_on_date_selects_exact_calendar_day(self):
        from datetime import datetime, timezone
        day = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d")
        self.db.insert(_item("On the day", score=8, hours_ago=48))
        self.db.insert(_item("Today instead", score=9, hours_ago=1))

        stories = select_stories(self.db, on_date=day, min_score=6, max_stories=5)

        titles = [p.title for p, _ in stories]
        self.assertIn("On the day", titles)
        self.assertNotIn("Today instead", titles)


class PreviouslyCoveredUrlsTests(unittest.TestCase):
    def test_reads_story_urls_from_recent_scripts(self):
        import json as _json
        from datetime import datetime, timezone
        from ainews.processing.video_script import previously_covered_urls

        tmp = Path(tempfile.mkdtemp())
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with open(tmp / f"{today}.json", "w", encoding="utf-8") as f:
            _json.dump({"meta": {"story_urls": ["https://a", "https://b"]}}, f)
        with open(tmp / "2020-01-01.json", "w", encoding="utf-8") as f:
            _json.dump({"meta": {"story_urls": ["https://ancient"]}}, f)

        covered = previously_covered_urls(tmp, days=14)

        self.assertEqual(covered, {"https://a", "https://b"})

    def test_missing_dir_returns_empty(self):
        from ainews.processing.video_script import previously_covered_urls
        self.assertEqual(previously_covered_urls(Path("/nonexistent-dir-xyz")), set())
