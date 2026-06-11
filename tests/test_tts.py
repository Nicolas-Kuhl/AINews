"""Tests for the voiceover synthesis module (Stage 2 of the video pipeline).

Uses a fake Polly client — no AWS access or boto3 needed.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from ainews.video.tts import (
    _marks_duration_seconds,
    iter_sections,
    synthesize_samples,
    synthesize_script,
)


def _marks_jsonl(word_times_ms):
    return "\n".join(
        json.dumps({"time": t, "type": "word", "value": f"w{i}"})
        for i, t in enumerate(word_times_ms)
    )


class _FakePolly:
    """Returns canned MP3 bytes and speech marks; records calls."""

    def __init__(self, fail_marks=False, fail_engines=()):
        self.fail_marks = fail_marks
        self.fail_engines = set(fail_engines)
        self.calls = []

    def synthesize_speech(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["Engine"] in self.fail_engines:
            raise RuntimeError(f"engine {kwargs['Engine']} not available")
        if kwargs["OutputFormat"] == "json":
            if self.fail_marks:
                raise RuntimeError("speech marks not supported for this engine")
            body = _marks_jsonl([0, 800, 1600]).encode("utf-8")
        else:
            body = b"ID3fake-mp3-bytes"
        return {"AudioStream": io.BytesIO(body)}


def _script(n_segments=2):
    return {
        "title": "Test Episode",
        "cold_open": "Welcome to the show.",
        "segments": [
            {"slug": f"story-{i}", "headline": f"H{i}", "source": "S",
             "url": "https://example.com", "narration": f"Narration {i}."}
            for i in range(n_segments)
        ],
        "sign_off": "Goodbye.",
        "meta": {"target_minutes": 5},
    }


class IterSectionsTests(unittest.TestCase):
    def test_orders_cold_open_segments_sign_off(self):
        keys = [k for k, _ in iter_sections(_script(2))]
        self.assertEqual(keys, ["00-cold_open", "01-story-0", "02-story-1", "03-sign_off"])

    def test_section_text_matches(self):
        sections = dict(iter_sections(_script(1)))
        self.assertEqual(sections["00-cold_open"], "Welcome to the show.")
        self.assertEqual(sections["02-sign_off"], "Goodbye.")


class MarksDurationTests(unittest.TestCase):
    def test_duration_is_last_mark_plus_pad(self):
        self.assertEqual(_marks_duration_seconds(_marks_jsonl([0, 500, 2000])), 2.4)

    def test_empty_marks_returns_none(self):
        self.assertIsNone(_marks_duration_seconds(""))
        self.assertIsNone(_marks_duration_seconds("not json"))


class SynthesizeScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def test_writes_audio_marks_and_manifest(self):
        polly = _FakePolly()
        manifest = synthesize_script(_script(2), self.tmpdir, polly=polly)

        self.assertEqual(len(manifest["sections"]), 4)
        for entry in manifest["sections"]:
            self.assertTrue((self.tmpdir / entry["audio"]).exists())
            self.assertTrue((self.tmpdir / entry["marks"]).exists())
            self.assertEqual(entry["duration_seconds"], 2.0)
        with open(self.tmpdir / "manifest.json", encoding="utf-8") as f:
            on_disk = json.load(f)
        self.assertEqual(on_disk["title"], "Test Episode")
        self.assertEqual(on_disk["total_duration_seconds"], 8.0)
        # 2 calls per section: audio + marks
        self.assertEqual(len(polly.calls), 8)

    def test_marks_failure_is_nonfatal(self):
        polly = _FakePolly(fail_marks=True)
        manifest = synthesize_script(_script(1), self.tmpdir, polly=polly)

        for entry in manifest["sections"]:
            self.assertTrue((self.tmpdir / entry["audio"]).exists())
            self.assertIsNone(entry["marks"])
            self.assertIsNone(entry["duration_seconds"])
        self.assertIsNone(manifest["total_duration_seconds"])

    def test_voice_and_engine_passed_through(self):
        polly = _FakePolly()
        synthesize_script(_script(1), self.tmpdir, polly=polly,
                          voice="Gregory", engine="long-form")
        self.assertTrue(all(c["VoiceId"] == "Gregory" for c in polly.calls))
        self.assertTrue(all(c["Engine"] == "long-form" for c in polly.calls))


class SynthesizeSamplesTests(unittest.TestCase):
    def test_failed_engine_skipped_others_written(self):
        tmpdir = Path(tempfile.mkdtemp())
        polly = _FakePolly(fail_engines={"long-form"})
        candidates = [("Ruth", "generative"), ("Gregory", "long-form"), ("Joanna", "neural")]

        written = synthesize_samples(tmpdir, candidates=candidates, polly=polly)

        names = [p.name for p in written]
        self.assertEqual(names, ["sample-generative-Ruth.mp3", "sample-neural-Joanna.mp3"])


if __name__ == "__main__":
    unittest.main()
