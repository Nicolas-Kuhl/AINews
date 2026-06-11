"""Tests for video pipeline disk housekeeping."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from ainews.video.maintenance import prune_old_episodes


class PruneTests(unittest.TestCase):
    def setUp(self):
        base = Path(tempfile.mkdtemp())
        self.videos = base / "videos"
        self.audio = base / "audio"
        self.staged = base / "staged"
        for d in (self.videos, self.audio, self.staged):
            d.mkdir()
        self.now = datetime(2026, 6, 11, tzinfo=timezone.utc)

    def test_prunes_by_age_and_kind(self):
        (self.videos / "2026-06-10.mp4").write_bytes(b"new")
        (self.videos / "2026-04-01.mp4").write_bytes(b"old")
        (self.videos / "feed.xml").write_text("<rss/>")
        (self.audio / "2026-06-10").mkdir()
        (self.audio / "2026-05-20").mkdir()
        (self.staged / "2026-05-20").mkdir()

        removed = prune_old_episodes(
            self.videos, self.audio, self.staged,
            keep_video_days=30, keep_audio_days=7, now=self.now,
        )

        self.assertEqual(sorted(removed), ["2026-04-01.mp4", "2026-05-20/", "2026-05-20/"])
        self.assertTrue((self.videos / "2026-06-10.mp4").exists())
        self.assertTrue((self.videos / "feed.xml").exists())
        self.assertTrue((self.audio / "2026-06-10").exists())
        self.assertFalse((self.audio / "2026-05-20").exists())

    def test_nonexistent_dirs_are_fine(self):
        removed = prune_old_episodes(
            Path("/nope-1"), Path("/nope-2"), Path("/nope-3"), now=self.now,
        )
        self.assertEqual(removed, [])


if __name__ == "__main__":
    unittest.main()
