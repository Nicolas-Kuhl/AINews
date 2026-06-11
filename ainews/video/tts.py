"""Voiceover synthesis — turns an episode script into per-section audio.

Stage 2 of the daily video pipeline. Takes the script JSON produced by
``ainews.processing.video_script`` and synthesizes one MP3 per narration
section (cold open, each segment, sign-off) with Amazon Polly, using the
EC2 instance role for credentials — no API keys on disk.

Per-section files (rather than one long take) give the renderer exact
durations for timing the visuals. Alongside each MP3 the module requests
word-level *speech marks* — timestamps for every spoken word — which drive
synced on-screen captions in Stage 3. Not every Polly engine supports
speech marks; when the request fails the section simply ships without
marks and the renderer falls back to unsynced text.

Everything is written to ``<output_dir>/<episode-date>/`` plus a
``manifest.json`` describing the sections in playback order.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_VOICE = "Olivia"  # en-AU generative — the show's host voice
DEFAULT_ENGINE = "generative"
# Generative and long-form engines have limited regional availability;
# us-east-1 has every engine and voice. TTS is offline work — cross-region
# latency is irrelevant.
DEFAULT_REGION = "us-east-1"

# Sampler candidates: (voice, engine) pairs worth auditioning for a daily
# news show. All available in us-east-1.
VOICE_CANDIDATES = [
    ("Ruth", "generative"),
    ("Matthew", "generative"),
    ("Stephen", "generative"),
    ("Amy", "generative"),      # en-GB
    ("Danielle", "long-form"),
    ("Gregory", "long-form"),
    ("Matthew", "neural"),
    ("Joanna", "neural"),
]

SAMPLE_TEXT = (
    "Anthropic just dropped a stat that should either excite you or keep "
    "you up at night: over eighty percent of the code they merge is now "
    "written by Claude, not humans. Today we're talking about machines "
    "that code themselves, benchmarks that lie, and why your AI assistant "
    "might be quietly sabotaging you. Let's get into it."
)


def make_polly_client(region: str = DEFAULT_REGION):
    """Build a boto3 Polly client (imported lazily so tests need no boto3)."""
    import boto3

    return boto3.client("polly", region_name=region)


def iter_sections(script: dict) -> "list[tuple[str, str]]":
    """Flatten a script into ordered (section_key, narration_text) pairs."""
    sections = [("00-cold_open", script["cold_open"])]
    for i, seg in enumerate(script.get("segments", []), 1):
        slug = seg.get("slug", f"story-{i}")
        sections.append((f"{i:02d}-{slug}", seg["narration"]))
    sections.append((f"{len(sections):02d}-sign_off", script["sign_off"]))
    return sections


def _marks_duration_seconds(marks_jsonl: str) -> Optional[float]:
    """Approximate audio duration from the last speech mark (+ breath pad)."""
    last_ms = None
    for line in marks_jsonl.strip().splitlines():
        try:
            mark = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(mark.get("time"), (int, float)):
            last_ms = mark["time"]
    if last_ms is None:
        return None
    return round(last_ms / 1000 + 0.4, 2)


def synthesize_section(
    polly,
    text: str,
    *,
    voice: str,
    engine: str,
    audio_path: Path,
    marks_path: Path,
) -> dict:
    """Synthesize one narration section: MP3 plus (best-effort) word marks.

    Returns a manifest entry. Raises on audio-synthesis failure — an episode
    with a missing section is not shippable — but missing speech marks only
    log a warning.
    """
    response = polly.synthesize_speech(
        Engine=engine,
        VoiceId=voice,
        OutputFormat="mp3",
        Text=text,
        TextType="text",
    )
    audio_path.write_bytes(response["AudioStream"].read())

    marks_file = None
    duration = None
    try:
        marks_response = polly.synthesize_speech(
            Engine=engine,
            VoiceId=voice,
            OutputFormat="json",
            SpeechMarkTypes=["word"],
            Text=text,
            TextType="text",
        )
        marks_jsonl = marks_response["AudioStream"].read().decode("utf-8")
        marks_path.write_text(marks_jsonl, encoding="utf-8")
        marks_file = marks_path.name
        duration = _marks_duration_seconds(marks_jsonl)
    except Exception as exc:  # noqa: BLE001 — marks are an enhancement, not a requirement
        logger.warning(
            "Speech marks unavailable for %s (engine=%s): %s — captions will be unsynced",
            audio_path.name, engine, exc,
        )

    return {
        "audio": audio_path.name,
        "marks": marks_file,
        "duration_seconds": duration,
        "characters": len(text),
    }


def synthesize_script(
    script: dict,
    output_dir: Path,
    *,
    voice: str = DEFAULT_VOICE,
    engine: str = DEFAULT_ENGINE,
    region: str = DEFAULT_REGION,
    polly=None,
    logger_: Optional[logging.Logger] = None,
) -> dict:
    """Synthesize every section of an episode script.

    Writes ``<key>.mp3`` / ``<key>.marks.jsonl`` per section plus a
    ``manifest.json``, and returns the manifest dict.
    """
    log = logger_ or logger
    polly = polly or make_polly_client(region)
    output_dir.mkdir(parents=True, exist_ok=True)

    entries = []
    total_chars = 0
    for key, text in iter_sections(script):
        entry = synthesize_section(
            polly, text,
            voice=voice, engine=engine,
            audio_path=output_dir / f"{key}.mp3",
            marks_path=output_dir / f"{key}.marks.jsonl",
        )
        entry["key"] = key
        entries.append(entry)
        total_chars += entry["characters"]
        log.info("  [TTS] %s — %s chars, %.1fs", key, entry["characters"],
                 entry["duration_seconds"] or -1)

    known = [e["duration_seconds"] for e in entries if e["duration_seconds"]]
    manifest = {
        "title": script.get("title", ""),
        "voice": voice,
        "engine": engine,
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
    *,
    text: str = SAMPLE_TEXT,
    candidates: "Optional[list[tuple[str, str]]]" = None,
    region: str = DEFAULT_REGION,
    polly=None,
) -> "list[Path]":
    """Render the same paragraph in several voices so a human can pick one."""
    polly = polly or make_polly_client(region)
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for voice, engine in candidates or VOICE_CANDIDATES:
        path = output_dir / f"sample-{engine}-{voice}.mp3"
        try:
            response = polly.synthesize_speech(
                Engine=engine, VoiceId=voice, OutputFormat="mp3",
                Text=text, TextType="text",
            )
            path.write_bytes(response["AudioStream"].read())
            written.append(path)
            logger.info("  [TTS] sample written: %s", path.name)
        except Exception as exc:  # noqa: BLE001 — keep auditioning the rest
            logger.warning("  [TTS] sample failed for %s/%s: %s", engine, voice, exc)
    return written
