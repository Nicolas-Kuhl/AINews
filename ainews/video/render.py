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


_WORD_CLEAN_RE = __import__("re").compile(r"[^a-z0-9]+")


def _norm_word(word: str) -> str:
    return _WORD_CLEAN_RE.sub("", word.lower())


def load_word_marks(marks_path: Path) -> "list[tuple[float, str]]":
    """Parse a marks JSONL file into (seconds, normalized_word) tuples."""
    out = []
    for line in marks_path.read_text(encoding="utf-8").splitlines():
        try:
            mark = json.loads(line)
        except json.JSONDecodeError:
            continue
        if mark.get("type") == "word" and isinstance(mark.get("time"), (int, float)):
            w = _norm_word(str(mark.get("value", "")))
            if w:
                out.append((mark["time"] / 1000, w))
    return out


def bullet_reveal_times(
    bullets: "list[dict]",
    marks: "list[tuple[float, str]]",
    duration_seconds: float,
) -> "list[dict]":
    """Resolve each bullet's reveal time from its narration anchor phrase.

    Anchors are matched as word sequences against the timestamped narration,
    searching forward from the previous bullet's position (bullets arrive in
    narration order). Unmatched anchors fall back to even spacing so a sloppy
    anchor degrades gracefully instead of stacking everything at zero.
    """
    words = [w for _, w in marks]
    resolved: "list[Optional[float]]" = []
    search_from = 0
    for bullet in bullets:
        anchor = [w for w in (_norm_word(t) for t in bullet["anchor"].split()) if w]
        found: Optional[float] = None
        if anchor:
            for i in range(search_from, len(words) - len(anchor) + 1):
                if words[i : i + len(anchor)] == anchor:
                    found = marks[i][0]
                    search_from = i + len(anchor)
                    break
        resolved.append(found)

    n = len(bullets)
    out = []
    for i, (bullet, t) in enumerate(zip(bullets, resolved)):
        if t is None:
            t = duration_seconds * (i + 1) / (n + 1)
            logger.warning(
                "Bullet anchor %r not found in narration marks — using fallback %.1fs",
                bullet["anchor"], t,
            )
        out.append({"text": bullet["text"], "revealAtSeconds": round(t, 2)})
    return out


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
    intro_audio: Optional[str] = None,
    intro_duration: float = 5.0,
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
            bullets = seg.get("bullets") or []
            if bullets:
                marks: "list[tuple[float, str]]" = []
                if entry.get("marks"):
                    marks_path = audio_dir / entry["marks"]
                    if marks_path.exists():
                        marks = load_word_marks(marks_path)
                section["bullets"] = bullet_reveal_times(bullets, marks, duration)
        sections.append(section)

    if seg_idx != len(segments):
        raise ValueError(
            f"Script has {len(segments)} segments but audio manifest only "
            f"covered {seg_idx}"
        )

    if intro_audio:
        # Musical ident before the cold open. The audio path is a site-bundled
        # static asset (renderer/public/...), not per-episode audio.
        sections.insert(0, {
            "kind": "intro",
            "key": "intro",
            "audio": intro_audio,
            "durationSeconds": intro_duration,
        })

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
