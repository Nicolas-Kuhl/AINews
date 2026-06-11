"""Render-manifest assembly — bridges Python pipeline output to the Remotion renderer.

Stage 3 glue. Combines the episode script (Stage 1) and the voiceover
manifest (Stage 2) into the props JSON the Remotion composition consumes:
one entry per section with audio path, exact duration, and display copy.

Durations come from the voiceover manifest when the TTS engine provided
speech marks; otherwise they're measured from the MP3 files directly
(mutagen) — the generative engine we use for the show voice doesn't
emit marks.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

DEFAULT_TAGLINE = "AI news. Daily. Slightly irreverent."
DEFAULT_SITE_URL = "ainews.eyrean.com"


def mp3_duration_seconds(path: Path) -> float:
    """Measure MP3 duration (lazy import keeps mutagen optional for tests)."""
    from mutagen.mp3 import MP3

    return float(MP3(str(path)).info.length)


def _section_kind(key: str) -> str:
    if key.endswith("cold_open"):
        return "cold_open"
    if key.endswith("sign_off"):
        return "sign_off"
    return "segment"


def build_render_manifest(
    script: dict,
    audio_manifest: dict,
    audio_dir: Path,
    *,
    audio_rel_prefix: str,
    show_name: str = "The Daily Prompt",
    date: str = "",
    tagline: str = DEFAULT_TAGLINE,
    site_url: str = DEFAULT_SITE_URL,
    duration_fn: Optional[Callable[[Path], float]] = None,
) -> dict:
    """Build the Remotion props dict for one episode.

    ``audio_rel_prefix`` is the path prefix under renderer/public where the
    audio files will live (e.g. ``audio/2026-06-10``).
    """
    measure = duration_fn or mp3_duration_seconds
    segments = script.get("segments", [])

    sections = []
    seg_idx = 0
    for entry in audio_manifest["sections"]:
        key = entry["key"]
        kind = _section_kind(key)
        duration = entry.get("duration_seconds")
        if not duration:
            duration = round(measure(audio_dir / entry["audio"]), 2)

        section: dict = {
            "kind": kind,
            "key": key,
            "audio": f"{audio_rel_prefix}/{entry['audio']}",
            "durationSeconds": duration,
        }
        if kind == "segment":
            if seg_idx >= len(segments):
                raise ValueError(
                    f"Audio manifest has more segments than the script "
                    f"({len(segments)}) — key {key!r} has no matching script segment"
                )
            seg = segments[seg_idx]
            seg_idx += 1
            section["headline"] = seg["headline"]
            section["source"] = seg["source"]
            section["index"] = seg_idx
        sections.append(section)

    if seg_idx != len(segments):
        raise ValueError(
            f"Script has {len(segments)} segments but audio manifest only "
            f"covered {seg_idx}"
        )

    return {
        "date": date,
        "title": script.get("title", ""),
        "showName": show_name,
        "tagline": tagline,
        "siteUrl": site_url,
        "segmentCount": len(segments),
        "sections": sections,
    }


def write_render_manifest(manifest: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return path
