"""Voiceover synthesis — turns an episode script into per-section audio.

Stage 2 of the daily video pipeline. Takes the script JSON produced by
``ainews.processing.video_script`` and synthesizes one MP3 per narration
section (cold open, each segment, sign-off), plus word-level timing marks
that drive synced captions in Stage 3.

Two providers behind one interface:

- **ElevenLabs** (default) — the show voice. Uses the ``with-timestamps``
  endpoint so audio and word marks come from a single call and always
  agree. Needs ``ELEVENLABS_API_KEY`` in the environment (or
  ``tts.api_key`` in config — prefer the env var; the server's ``.env``
  is the right home).
- **Amazon Polly** — fallback / no-key option using the EC2 instance
  role. Polly's generative engine does not support speech marks, so
  sections may ship without marks.

Per-section files (rather than one long take) give the renderer exact
durations for timing the visuals. Everything is written to
``<output_dir>/<episode-date>/`` plus a ``manifest.json`` describing the
sections in playback order — the marks format is Polly-style JSONL
(``{"time": ms, "type": "word", "value": ...}``) regardless of provider.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "elevenlabs"

# --- ElevenLabs defaults ---------------------------------------------------
DEFAULT_ELEVENLABS_MODEL = "eleven_multilingual_v2"
ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1"

# --- Polly defaults (fallback provider) ------------------------------------
DEFAULT_POLLY_VOICE = "Olivia"  # en-AU generative
DEFAULT_POLLY_ENGINE = "generative"
DEFAULT_POLLY_REGION = "us-east-1"

POLLY_VOICE_CANDIDATES = [
    ("Olivia", "generative"),
    ("Ruth", "generative"),
    ("Matthew", "generative"),
    ("Danielle", "long-form"),
]

SAMPLE_TEXT = (
    "Anthropic just dropped a stat that should either excite you or keep "
    "you up at night: over eighty percent of the code they merge is now "
    "written by Claude, not humans. Today we're talking about machines "
    "that code themselves, benchmarks that lie, and why your AI assistant "
    "might be quietly sabotaging you. Let's get into it."
)


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

class ElevenLabsTTS:
    """ElevenLabs text-to-speech with word-level timestamps."""

    def __init__(
        self,
        api_key: str,
        voice: str,
        *,
        model_id: str = DEFAULT_ELEVENLABS_MODEL,
        speed: float = 1.0,
        http=None,
    ):
        import httpx

        self.api_key = api_key
        self.model_id = model_id
        self.speed = speed
        self.http = http or httpx.Client(
            base_url=ELEVENLABS_BASE_URL,
            headers={"xi-api-key": api_key},
            timeout=180,
        )
        self.voice_id = self._resolve_voice(voice)
        self.label = f"{voice} (elevenlabs/{model_id}, speed={speed})"

    def _resolve_voice(self, voice: str) -> str:
        """Accept either a raw voice_id or a human voice name."""
        # Voice IDs are 20+ char alphanumeric tokens with no spaces;
        # anything else is treated as a name to look up.
        if len(voice) >= 20 and voice.isalnum():
            return voice
        for v in self.list_voices():
            if v["name"].lower() == voice.lower():
                return v["voice_id"]
        raise ValueError(
            f"ElevenLabs voice {voice!r} not found in this account. "
            f"Run generate_voiceover.py --sample to list and audition voices."
        )

    def list_voices(self) -> "list[dict]":
        resp = self.http.get("/voices")
        resp.raise_for_status()
        return [
            {
                "voice_id": v["voice_id"],
                "name": v["name"],
                "labels": v.get("labels") or {},
            }
            for v in resp.json().get("voices", [])
        ]

    def synthesize(self, text: str) -> "tuple[bytes, Optional[str]]":
        """Return (mp3_bytes, word_marks_jsonl). One call, always in sync."""
        payload: dict = {"text": text, "model_id": self.model_id}
        if self.speed and self.speed != 1.0:
            payload["voice_settings"] = {"speed": self.speed}
        resp = self.http.post(
            f"/text-to-speech/{self.voice_id}/with-timestamps",
            params={"output_format": "mp3_44100_128"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        audio = base64.b64decode(data["audio_base64"])
        marks = _alignment_to_word_marks(data.get("alignment"))
        return audio, marks


class PollyTTS:
    """Amazon Polly fallback using instance-role credentials."""

    def __init__(
        self,
        *,
        voice: str = DEFAULT_POLLY_VOICE,
        engine: str = DEFAULT_POLLY_ENGINE,
        region: str = DEFAULT_POLLY_REGION,
        client=None,
    ):
        self.voice = voice
        self.engine = engine
        self.client = client or _make_polly_client(region)
        self.label = f"{voice} (polly/{engine})"

    def synthesize(self, text: str) -> "tuple[bytes, Optional[str]]":
        resp = self.client.synthesize_speech(
            Engine=self.engine, VoiceId=self.voice,
            OutputFormat="mp3", Text=text, TextType="text",
        )
        audio = resp["AudioStream"].read()
        marks = None
        try:
            marks_resp = self.client.synthesize_speech(
                Engine=self.engine, VoiceId=self.voice,
                OutputFormat="json", SpeechMarkTypes=["word"],
                Text=text, TextType="text",
            )
            marks = marks_resp["AudioStream"].read().decode("utf-8")
        except Exception as exc:  # noqa: BLE001 — marks are an enhancement
            logger.warning("Polly speech marks unavailable (engine=%s): %s",
                           self.engine, exc)
        return audio, marks


def _make_polly_client(region: str):
    import boto3

    return boto3.client("polly", region_name=region)


def _alignment_to_word_marks(alignment: Optional[dict]) -> Optional[str]:
    """Convert ElevenLabs character alignment to Polly-style word marks JSONL.

    The renderer consumes one format regardless of provider:
    ``{"time": <ms>, "type": "word", "value": <word>}`` per line, plus a
    final ``{"time": <ms>, "type": "end"}`` carrying the audio end time
    (ElevenLabs gives exact end times; use them for duration).
    """
    if not alignment:
        return None
    chars = alignment.get("characters") or []
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []
    if not chars or len(chars) != len(starts):
        return None

    lines = []
    word = ""
    word_start = 0.0
    for i, ch in enumerate(chars):
        if ch.isspace():
            if word:
                lines.append(json.dumps(
                    {"time": int(word_start * 1000), "type": "word", "value": word}
                ))
                word = ""
        else:
            if not word:
                word_start = starts[i]
            word += ch
    if word:
        lines.append(json.dumps(
            {"time": int(word_start * 1000), "type": "word", "value": word}
        ))
    if ends:
        lines.append(json.dumps({"time": int(ends[-1] * 1000), "type": "end"}))
    return "\n".join(lines)


def make_tts(tts_cfg: dict, *, provider: Optional[str] = None):
    """Build the configured TTS provider; fall back to Polly without a key."""
    provider = provider or tts_cfg.get("provider", DEFAULT_PROVIDER)
    if provider == "elevenlabs":
        api_key = (
            os.environ.get("ELEVENLABS_API_KEY")
            or tts_cfg.get("api_key")
        )
        if not api_key:
            logger.warning(
                "No ELEVENLABS_API_KEY found — falling back to Amazon Polly. "
                "Add the key to the server's .env to use the ElevenLabs voice."
            )
            return PollyTTS(
                voice=tts_cfg.get("polly_voice", DEFAULT_POLLY_VOICE),
                engine=tts_cfg.get("polly_engine", DEFAULT_POLLY_ENGINE),
                region=tts_cfg.get("region", DEFAULT_POLLY_REGION),
            )
        voice = tts_cfg.get("voice")
        if not voice:
            raise ValueError(
                "tts.voice is not set. Run generate_voiceover.py --sample to "
                "audition the account's voices, then set tts.voice in config.yaml."
            )
        return ElevenLabsTTS(
            api_key, voice,
            model_id=tts_cfg.get("model", DEFAULT_ELEVENLABS_MODEL),
            speed=float(tts_cfg.get("speed", 1.0)),
        )
    if provider == "polly":
        return PollyTTS(
            voice=tts_cfg.get("polly_voice", tts_cfg.get("voice", DEFAULT_POLLY_VOICE)),
            engine=tts_cfg.get("polly_engine", tts_cfg.get("engine", DEFAULT_POLLY_ENGINE)),
            region=tts_cfg.get("region", DEFAULT_POLLY_REGION),
        )
    raise ValueError(f"Unknown TTS provider: {provider!r}")


# ---------------------------------------------------------------------------
# Episode synthesis (provider-agnostic)
# ---------------------------------------------------------------------------

def iter_sections(script: dict) -> "list[tuple[str, str]]":
    """Flatten a script into ordered (section_key, narration_text) pairs."""
    sections = [("00-cold_open", script["cold_open"])]
    for i, seg in enumerate(script.get("segments", []), 1):
        slug = seg.get("slug", f"story-{i}")
        sections.append((f"{i:02d}-{slug}", seg["narration"]))
    sections.append((f"{len(sections):02d}-sign_off", script["sign_off"]))
    return sections


def _marks_duration_seconds(marks_jsonl: str) -> Optional[float]:
    """Audio duration from the marks: exact "end" mark if present, else the
    last word time plus a breath pad."""
    last_ms = None
    end_ms = None
    for line in marks_jsonl.strip().splitlines():
        try:
            mark = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(mark.get("time"), (int, float)):
            continue
        if mark.get("type") == "end":
            end_ms = mark["time"]
        else:
            last_ms = mark["time"]
    if end_ms is not None:
        return round(end_ms / 1000, 2)
    if last_ms is not None:
        return round(last_ms / 1000 + 0.4, 2)
    return None


def synthesize_script(
    script: dict,
    output_dir: Path,
    *,
    tts,
    logger_: Optional[logging.Logger] = None,
) -> dict:
    """Synthesize every section of an episode script with the given provider.

    Writes ``<key>.mp3`` / ``<key>.marks.jsonl`` per section plus a
    ``manifest.json``, and returns the manifest dict.
    """
    log = logger_ or logger
    output_dir.mkdir(parents=True, exist_ok=True)

    entries = []
    total_chars = 0
    for key, text in iter_sections(script):
        audio, marks = tts.synthesize(text)
        audio_path = output_dir / f"{key}.mp3"
        audio_path.write_bytes(audio)
        marks_file = None
        duration = None
        if marks:
            marks_path = output_dir / f"{key}.marks.jsonl"
            marks_path.write_text(marks, encoding="utf-8")
            marks_file = marks_path.name
            duration = _marks_duration_seconds(marks)
        entries.append({
            "key": key,
            "audio": audio_path.name,
            "marks": marks_file,
            "duration_seconds": duration,
            "characters": len(text),
        })
        total_chars += len(text)
        log.info("  [TTS] %s — %s chars, %.1fs", key, len(text), duration or -1)

    known = [e["duration_seconds"] for e in entries if e["duration_seconds"]]
    manifest = {
        "title": script.get("title", ""),
        "voice": tts.label,
        "sections": entries,
        "total_characters": total_chars,
        "total_duration_seconds": round(sum(known), 1) if len(known) == len(entries) else None,
        "source_meta": script.get("meta", {}),
    }
    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    log.info("Voiceover manifest written: %s (%d sections, %d chars)",
             manifest_path, len(entries), total_chars)
    return manifest


def synthesize_samples(
    output_dir: Path,
    providers: "list",
    *,
    text: str = SAMPLE_TEXT,
) -> "list[Path]":
    """Render the same paragraph with each provider so a human can pick."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for tts in providers:
        safe = tts.label.replace("/", "-").replace(" ", "").replace("(", "-").replace(")", "")
        path = output_dir / f"sample-{safe}.mp3"
        try:
            audio, _marks = tts.synthesize(text)
            path.write_bytes(audio)
            written.append(path)
            logger.info("  [TTS] sample written: %s", path.name)
        except Exception as exc:  # noqa: BLE001 — keep auditioning the rest
            logger.warning("  [TTS] sample failed for %s: %s", tts.label, exc)
    return written
