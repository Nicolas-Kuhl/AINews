"""Tests for the render-manifest assembly (Stage 3 glue)."""

from __future__ import annotations

import unittest
from pathlib import Path

from ainews.video.render import build_render_manifest


def _script():
    return {
        "title": "Test Episode",
        "cold_open": "Hi.",
        "segments": [
            {"slug": "a", "headline": "Headline A", "source": "Src A",
             "url": "https://example.com/a", "narration": "..."},
            {"slug": "b", "headline": "Headline B", "source": "Src B",
             "url": "https://example.com/b", "narration": "..."},
        ],
        "sign_off": "Bye.",
    }


def _audio_manifest(durations=(3.0, 10.0, 12.0, 2.5)):
    keys = ["00-cold_open", "01-a", "02-b", "03-sign_off"]
    return {
        "sections": [
            {"key": k, "audio": f"{k}.mp3", "marks": None,
             "duration_seconds": d, "characters": 100}
            for k, d in zip(keys, durations)
        ]
    }


class BuildRenderManifestTests(unittest.TestCase):
    def test_sections_kinds_and_copy(self):
        manifest = build_render_manifest(
            _script(), _audio_manifest(), Path("."),
            audio_rel_prefix="audio/2026-06-10", date="2026-06-10",
        )

        kinds = [s["kind"] for s in manifest["sections"]]
        self.assertEqual(kinds, ["cold_open", "segment", "segment", "sign_off"])
        seg1 = manifest["sections"][1]
        self.assertEqual(seg1["headline"], "Headline A")
        self.assertEqual(seg1["source"], "Src A")
        self.assertEqual(seg1["index"], 1)
        self.assertEqual(seg1["audio"], "audio/2026-06-10/01-a.mp3")
        self.assertEqual(manifest["segmentCount"], 2)
        self.assertEqual(manifest["title"], "Test Episode")

    def test_missing_durations_measured_via_duration_fn(self):
        audio = _audio_manifest(durations=(None, None, None, None))
        measured = []

        def fake_measure(path: Path) -> float:
            measured.append(path.name)
            return 7.77

        manifest = build_render_manifest(
            _script(), audio, Path("/tmp/audio"),
            audio_rel_prefix="audio/x", duration_fn=fake_measure,
        )

        self.assertEqual(len(measured), 4)
        self.assertTrue(all(s["durationSeconds"] == 7.77 for s in manifest["sections"]))

    def test_segment_count_mismatch_raises(self):
        audio = _audio_manifest()
        audio["sections"] = audio["sections"][:2] + audio["sections"][3:]  # drop one segment

        with self.assertRaises(ValueError):
            build_render_manifest(
                _script(), audio, Path("."), audio_rel_prefix="audio/x",
            )


if __name__ == "__main__":
    unittest.main()
