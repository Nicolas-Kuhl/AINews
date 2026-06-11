"""Tests for the episode podcast feed (video RSS with enclosures)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ainews.video.feed import build_feed_xml, collect_episodes, write_episode_feed


def _make_episode(videos: Path, scripts: Path, date: str, title: str = "Ep") -> None:
    (videos / f"{date}.mp4").write_bytes(b"\x00" * 1234)
    script = {
        "title": title,
        "cold_open": "Hello & welcome.",
        "segments": [
            {"headline": "A <big> story", "source": "Src", "url": "u", "narration": "n"},
        ],
        "sign_off": "Bye.",
        "meta": {"estimated_runtime_seconds": 291},
    }
    with open(scripts / f"{date}.json", "w", encoding="utf-8") as f:
        json.dump(script, f)


class CollectEpisodesTests(unittest.TestCase):
    def setUp(self):
        self.videos = Path(tempfile.mkdtemp())
        self.scripts = Path(tempfile.mkdtemp())

    def test_pairs_mp4_with_script_newest_first(self):
        _make_episode(self.videos, self.scripts, "2026-06-09", "First")
        _make_episode(self.videos, self.scripts, "2026-06-10", "Second")

        eps = collect_episodes(self.videos, self.scripts)

        self.assertEqual([e["date"] for e in eps], ["2026-06-10", "2026-06-09"])
        self.assertEqual(eps[0]["title"], "Second")
        self.assertEqual(eps[0]["size_bytes"], 1234)
        self.assertEqual(eps[0]["duration_seconds"], 291)

    def test_skips_orphan_mp4s_and_preview_frames(self):
        _make_episode(self.videos, self.scripts, "2026-06-10")
        (self.videos / "2026-06-11.mp4").write_bytes(b"x")  # no script
        (self.videos / "2026-06-10-frame80.png").write_bytes(b"x")

        eps = collect_episodes(self.videos, self.scripts)

        self.assertEqual([e["date"] for e in eps], ["2026-06-10"])


class FeedXmlTests(unittest.TestCase):
    def test_feed_structure_and_escaping(self):
        videos = Path(tempfile.mkdtemp())
        scripts = Path(tempfile.mkdtemp())
        _make_episode(videos, scripts, "2026-06-10", title="Bots & <Robots>")

        path, count = write_episode_feed(videos, scripts)
        xml = path.read_text(encoding="utf-8")

        self.assertEqual(count, 1)
        self.assertIn("<title>Bots &amp; &lt;Robots&gt;</title>", xml)
        self.assertIn(
            '<enclosure url="https://ainews.eyrean.com/videos/2026-06-10.mp4" '
            'length="1234" type="video/mp4"/>', xml,
        )
        self.assertIn('<guid isPermaLink="false">ainews-episode-2026-06-10</guid>', xml)
        self.assertIn("<itunes:duration>291</itunes:duration>", xml)
        self.assertIn("A &lt;big&gt; story (Src)", xml)

    def test_max_items_caps_feed(self):
        eps = [
            {"date": f"2026-06-{d:02d}", "title": "t", "description": "d",
             "duration_seconds": None, "size_bytes": 1,
             "pub_dt": __import__("datetime").datetime(2026, 6, d,
                tzinfo=__import__("datetime").timezone.utc)}
            for d in range(1, 11)
        ]
        xml = build_feed_xml(eps, max_items=3)
        self.assertEqual(xml.count("<item>"), 3)


if __name__ == "__main__":
    unittest.main()
