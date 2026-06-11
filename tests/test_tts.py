"""Tests for the voiceover synthesis module (Stage 2 of the video pipeline).

Uses fake providers/clients — no AWS, no ElevenLabs, no network.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from ainews.video.tts import (
    ElevenLabsTTS,
    PollyTTS,
    _alignment_to_word_marks,
    _marks_duration_seconds,
    iter_sections,
    make_tts,
    synthesize_script,
)


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


class _FakeTTS:
    label = "Fake (test)"

    def __init__(self, with_marks=True):
        self.with_marks = with_marks
        self.texts = []

    def synthesize(self, text):
        self.texts.append(text)
        marks = None
        if self.with_marks:
            marks = "\n".join([
                json.dumps({"time": 0, "type": "word", "value": "hi"}),
                json.dumps({"time": 1500, "type": "word", "value": "there"}),
                json.dumps({"time": 2000, "type": "end"}),
            ])
        return b"ID3fake-mp3", marks


class IterSectionsTests(unittest.TestCase):
    def test_orders_cold_open_segments_sign_off(self):
        keys = [k for k, _ in iter_sections(_script(2))]
        self.assertEqual(keys, ["00-cold_open", "01-story-0", "02-story-1", "03-sign_off"])


class MarksDurationTests(unittest.TestCase):
    def test_exact_end_mark_wins(self):
        marks = "\n".join([
            json.dumps({"time": 500, "type": "word", "value": "a"}),
            json.dumps({"time": 3210, "type": "end"}),
        ])
        self.assertEqual(_marks_duration_seconds(marks), 3.21)

    def test_falls_back_to_last_word_plus_pad(self):
        marks = json.dumps({"time": 2000, "type": "word", "value": "a"})
        self.assertEqual(_marks_duration_seconds(marks), 2.4)

    def test_empty_returns_none(self):
        self.assertIsNone(_marks_duration_seconds(""))


class AlignmentConversionTests(unittest.TestCase):
    def test_characters_fold_into_words(self):
        alignment = {
            "characters": list("hi yo"),
            "character_start_times_seconds": [0.0, 0.1, 0.2, 0.5, 0.6],
            "character_end_times_seconds": [0.1, 0.2, 0.5, 0.6, 0.9],
        }
        marks = _alignment_to_word_marks(alignment)
        lines = [json.loads(l) for l in marks.splitlines()]
        self.assertEqual(lines[0], {"time": 0, "type": "word", "value": "hi"})
        self.assertEqual(lines[1], {"time": 500, "type": "word", "value": "yo"})
        self.assertEqual(lines[2], {"time": 900, "type": "end"})

    def test_missing_alignment_returns_none(self):
        self.assertIsNone(_alignment_to_word_marks(None))
        self.assertIsNone(_alignment_to_word_marks({"characters": []}))


class ElevenLabsProviderTests(unittest.TestCase):
    class _FakeHttp:
        def __init__(self):
            self.requests = []

        def get(self, path):
            self.requests.append(("GET", path))

            class R:
                @staticmethod
                def raise_for_status():
                    pass

                @staticmethod
                def json():
                    return {"voices": [
                        {"voice_id": "v" * 20, "name": "Charlie",
                         "labels": {"accent": "australian"}},
                    ]}
            return R()

        def post(self, path, params=None, json_=None, **kwargs):
            self.requests.append(("POST", path))
            import base64 as b64

            class R:
                @staticmethod
                def raise_for_status():
                    pass

                @staticmethod
                def json():
                    return {
                        "audio_base64": b64.b64encode(b"mp3!").decode(),
                        "alignment": {
                            "characters": ["h", "i"],
                            "character_start_times_seconds": [0.0, 0.2],
                            "character_end_times_seconds": [0.2, 0.5],
                        },
                    }
            return R()

    def test_resolves_voice_name_and_synthesizes(self):
        http = self._FakeHttp()
        tts = ElevenLabsTTS("key", "Charlie", http=http)
        self.assertEqual(tts.voice_id, "v" * 20)

        audio, marks = tts.synthesize("hi")

        self.assertEqual(audio, b"mp3!")
        self.assertIn('"value": "hi"', marks)
        self.assertEqual(http.requests[-1][0], "POST")

    def test_raw_voice_id_skips_lookup(self):
        http = self._FakeHttp()
        tts = ElevenLabsTTS("key", "x" * 24, http=http)
        self.assertEqual(tts.voice_id, "x" * 24)
        self.assertEqual(http.requests, [])  # no /voices call

    def test_unknown_voice_name_raises(self):
        with self.assertRaises(ValueError):
            ElevenLabsTTS("key", "Nonexistent", http=self._FakeHttp())


class PollyProviderTests(unittest.TestCase):
    class _FakePolly:
        def __init__(self, fail_marks=False):
            self.fail_marks = fail_marks

        def synthesize_speech(self, **kwargs):
            if kwargs["OutputFormat"] == "json":
                if self.fail_marks:
                    raise RuntimeError("marks not supported")
                body = json.dumps({"time": 1000, "type": "word", "value": "w"}).encode()
            else:
                body = b"ID3polly"
            return {"AudioStream": io.BytesIO(body)}

    def test_synthesize_with_marks(self):
        tts = PollyTTS(client=self._FakePolly())
        audio, marks = tts.synthesize("hello")
        self.assertEqual(audio, b"ID3polly")
        self.assertIn('"value": "w"', marks)

    def test_marks_failure_returns_none(self):
        tts = PollyTTS(client=self._FakePolly(fail_marks=True))
        audio, marks = tts.synthesize("hello")
        self.assertEqual(audio, b"ID3polly")
        self.assertIsNone(marks)


class MakeTtsTests(unittest.TestCase):
    def test_no_key_falls_back_to_polly(self):
        import os
        old = os.environ.pop("ELEVENLABS_API_KEY", None)
        try:
            # Patch boto3 client creation away
            import ainews.video.tts as tts_mod
            orig = tts_mod._make_polly_client
            tts_mod._make_polly_client = lambda region: object()
            try:
                provider = make_tts({"provider": "elevenlabs"})
                self.assertIsInstance(provider, PollyTTS)
            finally:
                tts_mod._make_polly_client = orig
        finally:
            if old:
                os.environ["ELEVENLABS_API_KEY"] = old

    def test_unknown_provider_raises(self):
        with self.assertRaises(ValueError):
            make_tts({}, provider="espeak")


class SynthesizeScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def test_writes_audio_marks_and_manifest(self):
        fake = _FakeTTS()
        manifest = synthesize_script(_script(2), self.tmpdir, tts=fake)

        self.assertEqual(len(manifest["sections"]), 4)
        for entry in manifest["sections"]:
            self.assertTrue((self.tmpdir / entry["audio"]).exists())
            self.assertTrue((self.tmpdir / entry["marks"]).exists())
            self.assertEqual(entry["duration_seconds"], 2.0)  # exact end mark
        self.assertEqual(manifest["total_duration_seconds"], 8.0)
        self.assertEqual(manifest["voice"], "Fake (test)")

    def test_marks_optional(self):
        fake = _FakeTTS(with_marks=False)
        manifest = synthesize_script(_script(1), self.tmpdir, tts=fake)
        for entry in manifest["sections"]:
            self.assertIsNone(entry["marks"])
            self.assertIsNone(entry["duration_seconds"])
        self.assertIsNone(manifest["total_duration_seconds"])


if __name__ == "__main__":
    unittest.main()
