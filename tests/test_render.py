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


class BulletRevealTimesTests(unittest.TestCase):
    MARKS = [
        (0.0, "anthropic"), (0.4, "just"), (0.7, "dropped"), (1.1, "a"),
        (1.3, "stat"), (2.0, "eighty"), (2.4, "percent"), (2.9, "of"),
        (3.1, "code"), (4.0, "recursive"), (4.6, "selfimprovement"),
    ]

    def test_anchors_resolve_to_word_times(self):
        from ainews.video.render import bullet_reveal_times
        bullets = [
            {"text": "B1", "anchor": "just dropped"},
            {"text": "B2", "anchor": "eighty percent"},
            {"text": "B3", "anchor": "recursive self-improvement"},
        ]
        out = bullet_reveal_times(bullets, self.MARKS, 10.0)
        self.assertEqual([b["revealAtSeconds"] for b in out], [0.4, 2.0, 4.0])

    def test_search_moves_forward_only(self):
        from ainews.video.render import bullet_reveal_times
        marks = [(0.0, "code"), (1.0, "and"), (2.0, "code"), (3.0, "again")]
        bullets = [
            {"text": "B1", "anchor": "code"},
            {"text": "B2", "anchor": "code"},
        ]
        out = bullet_reveal_times(bullets, marks, 4.0)
        self.assertEqual([b["revealAtSeconds"] for b in out], [0.0, 2.0])

    def test_unmatched_anchor_falls_back_to_even_spacing(self):
        from ainews.video.render import bullet_reveal_times
        bullets = [
            {"text": "B1", "anchor": "nonexistent phrase"},
            {"text": "B2", "anchor": "also missing"},
        ]
        out = bullet_reveal_times(bullets, self.MARKS, 9.0)
        self.assertEqual([b["revealAtSeconds"] for b in out], [3.0, 6.0])

    def test_punctuation_and_case_insensitive(self):
        from ainews.video.render import bullet_reveal_times
        bullets = [{"text": "B", "anchor": "Eighty PERCENT,"}]
        out = bullet_reveal_times(bullets, self.MARKS, 10.0)
        self.assertEqual(out[0]["revealAtSeconds"], 2.0)


class ManifestBulletsTests(unittest.TestCase):
    def test_segment_bullets_resolved_from_marks_file(self):
        import json as _json
        import tempfile
        from ainews.video.render import build_render_manifest

        tmp = Path(tempfile.mkdtemp())
        marks = "\n".join([
            _json.dumps({"time": 0, "type": "word", "value": "hello"}),
            _json.dumps({"time": 1200, "type": "word", "value": "eighty"}),
            _json.dumps({"time": 1500, "type": "word", "value": "percent"}),
            _json.dumps({"time": 3000, "type": "end"}),
        ])
        (tmp / "01-a.marks.jsonl").write_text(marks, encoding="utf-8")

        script = _script()
        script["segments"][0]["bullets"] = [
            {"text": "Big number", "anchor": "eighty percent"},
        ]
        audio = _audio_manifest()
        audio["sections"][1]["marks"] = "01-a.marks.jsonl"

        manifest = build_render_manifest(
            script, audio, tmp, audio_rel_prefix="audio/x",
        )

        seg = manifest["sections"][1]
        self.assertEqual(seg["bullets"], [
            {"text": "Big number", "revealAtSeconds": 1.2},
        ])
