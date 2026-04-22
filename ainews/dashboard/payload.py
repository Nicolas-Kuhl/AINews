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


SourceType = str  # "Official" | "Web Scrape" | "Newsletter"


# Newsletters typically arrive via email ingestion — the source string is the
# newsletter name rather than a feed URL. Keep this list extensible.
_NEWSLETTER_HINTS = re.compile(
    r"\b(tldr|import ai|newsletter|substack|the batch|alphasignal|"
    r"superhuman( ai)?|the rundown|lenny|interconnects|one useful thing|"
    r"chain of thought|ahead of ai)\b",
    re.IGNORECASE,
)

# Official = first-party posts from AI labs / companies. Narrow allowlist —
# everything else falls through to "Web Scrape".
_OFFICIAL_HINTS = re.compile(
    r"\b(anthropic|openai|deepmind|google ai|google deepmind|"
    r"gemini news|claude status|github copilot|meta ai|microsoft ai|"
    r"nvidia (news|newsroom|blog)|cohere|mistral (ai|ai news)|"
    r"stability ai|aws (ml|ai)|apple ai|ibm research|hugging ?face blog)\b",
    re.IGNORECASE,
)


def _infer_source_type(source: str) -> SourceType:
    if _NEWSLETTER_HINTS.search(source):
        return "Newsletter"
    if _OFFICIAL_HINTS.search(source):
        return "Official"
    return "Web Scrape"


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


_CONFIG_CATEGORY_TO_TYPE: dict[str, SourceType] = {
    "trusted": "Official",
    "open": "Web Scrape",
    "newsletter": "Newsletter",
}


def derived_source_meta(
    source: str, *, config_type: SourceType | None = None
) -> dict[str, Any]:
    """Heuristic display metadata used as a fallback when the `sources` table
    has no entry for this source.

    Passing ``config_type`` forces the type (e.g. when the source matches a
    feed entry in ``config.yaml``), overriding the name-based heuristic.
    """
    return {
        "short": _short_for(source),
        "mark": _mark_for(source),
        "hue": _hue_for(source),
        "type": config_type or _infer_source_type(source),
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


def _config_type_map(config_feeds: Iterable[Mapping[str, Any]] | None) -> dict[str, SourceType]:
    """Return a ``source_name → SourceType`` map derived from the config feeds.

    Feed rows with ``category: trusted`` become Official, ``open`` becomes
    Web Scrape. Unrecognised categories are ignored (heuristic will run).
    """
    out: dict[str, SourceType] = {}
    for feed in config_feeds or ():
        name = (feed.get("name") or "").strip()
        cat = (feed.get("category") or "").strip().lower()
        mapped = _CONFIG_CATEGORY_TO_TYPE.get(cat)
        if name and mapped:
            out[name] = mapped
    return out


def ensure_source_metas(
    db,
    *,
    refresh_all: bool = False,
    config_feeds: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Populate the `sources` table with derived defaults for any source that
    does not yet have a row, and return the current metadata map.

    Passing ``refresh_all=True`` overwrites existing rows — use sparingly, it
    wipes operator edits. Passing ``config_feeds`` lets the config drive
    ``type`` authoritatively (trusted→Official, open→Web Scrape).
    """
    existing = db.get_source_metas()
    seen_sources = set(db.get_all_sources())
    config_types = _config_type_map(config_feeds)
    missing = seen_sources - set(existing.keys()) if not refresh_all else seen_sources
    for name in missing:
        derived = derived_source_meta(name, config_type=config_types.get(name))
        db.upsert_source_meta(
            name,
            short=derived["short"],
            mark=derived["mark"],
            hue=derived["hue"],
            type=derived["type"],
        )
    return db.get_source_metas() if missing else existing
