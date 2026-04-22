"""Enriched payload builder for the triage-console frontend component.

Phase 1 synthesizes source metadata (mark letter, hue, type) from the
``source`` string because there is no ``sources`` table yet — that lands
in Phase 2, at which point this module becomes a thin lookup.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from ainews.models import ProcessedNewsItem


SourceType = str  # "Official" | "Press" | "Research" | "Platform" | "Newsletter"


_PRESS_HINTS = re.compile(
    r"\b(techcrunch|verge|bloomberg|reuters|ars technica|wired|ft\.com|"
    r"information|venturebeat|cnbc|guardian|financial times|axios)\b",
    re.IGNORECASE,
)
_RESEARCH_HINTS = re.compile(r"\b(arxiv|nature|science|papers|acl|neurips)\b", re.IGNORECASE)
_PLATFORM_HINTS = re.compile(r"\b(hugging ?face|github|kaggle|replicate|fly\.io)\b", re.IGNORECASE)
_NEWSLETTER_HINTS = re.compile(r"\b(tldr|import ai|newsletter|substack|the batch)\b", re.IGNORECASE)


def _infer_source_type(source: str) -> SourceType:
    if _RESEARCH_HINTS.search(source):
        return "Research"
    if _PLATFORM_HINTS.search(source):
        return "Platform"
    if _NEWSLETTER_HINTS.search(source):
        return "Newsletter"
    if _PRESS_HINTS.search(source):
        return "Press"
    return "Official"


def _hue_for(source: str) -> int:
    digest = hashlib.md5(source.strip().lower().encode("utf-8")).digest()
    return digest[0] * 360 // 256


def _short_for(source: str) -> str:
    s = source.strip()
    # Strip common suffixes that add no signal
    s = re.sub(r"\s+(News|Blog|AI|Team)$", "", s)
    return s or source


def _mark_for(source: str) -> str:
    s = _short_for(source)
    if not s:
        return "?"
    parts = [p for p in re.split(r"[\s\-]+", s) if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    # Single word: first letter if the word is "normal", first two if short/lowercase
    word = parts[0]
    return word[0].upper() if len(word) > 2 else word[:2].capitalize()


def derived_source_meta(source: str) -> dict[str, Any]:
    """Heuristic display metadata used as a fallback when the `sources` table
    has no entry for this source."""
    return {
        "short": _short_for(source),
        "mark": _mark_for(source),
        "hue": _hue_for(source),
        "type": _infer_source_type(source),
    }


def source_meta(
    source: str,
    overrides: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return display metadata for a source name, preferring the `sources`
    table row (passed via ``overrides``) over the heuristic fallback."""
    if overrides and source in overrides:
        row = overrides[source]
        return {
            "short": row["short"],
            "mark": row["mark"],
            "hue": int(row["hue"]),
            "type": row["type"],
        }
    return derived_source_meta(source)


def _day_label(day_key: str, today: date) -> str:
    try:
        d = datetime.strptime(day_key, "%Y-%m-%d").date()
    except ValueError:
        return day_key
    if d == today:
        return "Today"
    if d == today - timedelta(days=1):
        return "Yesterday"
    return d.strftime("%A, %b %-d")


def _story_to_dict(
    primary: ProcessedNewsItem,
    related: Iterable[ProcessedNewsItem],
    overrides: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": primary.id,
        "title": primary.title,
        "url": primary.url,
        "source": primary.source,
        "published": primary.published.isoformat() if primary.published else None,
        "score": primary.score,
        "category": primary.category,
        "summary": primary.summary,
        "short_summary": primary.short_summary,
        "score_reasoning": primary.score_reasoning,
        "learning_objectives": primary.learning_objectives,
        "lo_generated_with_opus": primary.lo_generated_with_opus,
        "fetched_via": primary.fetched_via,
        "acknowledged": primary.acknowledged,
        "starred": primary.starred,
        "group_id": primary.group_id,
        "related": [
            {"source": r.source, "title": r.title, "url": r.url}
            for r in related
        ],
        "source_meta": source_meta(primary.source, overrides),
    }


def build_by_day_payload(
    by_day: Mapping[str, list[tuple[ProcessedNewsItem, list[ProcessedNewsItem]]]],
    *,
    today: date | None = None,
    source_metas: Mapping[str, Mapping[str, Any]] | None = None,
    day_briefs: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Serialize the output of :meth:`Database.query_by_day` for the component."""
    if today is None:
        today = datetime.now(timezone.utc).date()

    result: list[dict[str, Any]] = []
    for day_key, groups in by_day.items():
        stories = [
            _story_to_dict(primary, related, source_metas)
            for primary, related in groups
        ]
        result.append(
            {
                "date": day_key,
                "label": _day_label(day_key, today),
                "brief": (day_briefs or {}).get(day_key),
                "stories": stories,
            }
        )
    return result


def ensure_source_metas(db, *, refresh_all: bool = False) -> dict[str, dict[str, Any]]:
    """Populate the `sources` table with derived defaults for any source that
    does not yet have a row, and return the current metadata map.

    Passing ``refresh_all=True`` overwrites existing rows — use sparingly, it
    wipes operator edits.
    """
    existing = db.get_source_metas()
    seen_sources = set(db.get_all_sources())
    missing = seen_sources - set(existing.keys()) if not refresh_all else seen_sources
    for name in missing:
        derived = derived_source_meta(name)
        db.upsert_source_meta(
            name,
            short=derived["short"],
            mark=derived["mark"],
            hue=derived["hue"],
            type=derived["type"],
        )
    return db.get_source_metas() if missing else existing
