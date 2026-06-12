"""Assemble the daily newsletter from the same engine that drives the video.

Reuses the video pipeline's story selection (editorial weighting, frontier-lab
priority, clustering) but pulls MORE stories — a newsletter has room for ~12
where the episode has ~7 — and excludes stories carried by recent newsletters
so issues don't repeat day to day. The intro paragraph reuses the editorial
"morning brief" generator; the subject line borrows the day's punchy video
title when one exists.

Output is a plain dict (subject, intro, issue_date, video_url, stories[]) that
the renderer turns into HTML/text — no email or DB concerns here.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import anthropic

from ainews.processing.brief import generate_morning_brief
from ainews.processing.video_script import (
    previously_covered_urls,
    select_stories,
    story_signals,
)
from ainews.storage.database import Database

logger = logging.getLogger(__name__)

DEFAULT_SITE_URL = "https://ainews.eyrean.com"


def _story_entry(primary, related) -> dict:
    sig = story_signals(primary, related)
    sources = sorted({m.source for m in [primary, *related] if m.source})
    return {
        "headline": primary.title,
        "url": primary.url,
        "source": primary.source,
        "summary": (primary.short_summary or primary.summary or "").strip(),
        "category": primary.category,
        "score": primary.score,
        "sources": sources,
        "is_vendor_announcement": sig["is_vendor_announcement"],
        "source_count": sig["source_count"],
    }


def _subject_line(stories: list, video_title: Optional[str], issue_date: str) -> str:
    if video_title:
        return f"The Daily Prompt — {video_title}"
    if stories:
        return f"The Daily Prompt — {stories[0]['headline']}"
    return f"The Daily Prompt — {issue_date}"


def compose_newsletter(
    db: Database,
    client: anthropic.Anthropic,
    *,
    newsletter_dir: Path,
    scripts_dir: Path,
    on_date: Optional[str] = None,
    hours: int = 24,
    catchup_hours: int = 72,
    catchup_min_score: int = 8,
    min_score: int = 6,
    max_stories: int = 12,
    site_url: str = DEFAULT_SITE_URL,
    brief_model: str = "claude-sonnet-4-6",
    logger_: Optional[logging.Logger] = None,
) -> Optional[dict]:
    """Build the newsletter dict for the day, or None if nothing qualifies."""
    log = logger_ or logger
    exclude = previously_covered_urls(newsletter_dir)
    pairs = select_stories(
        db, hours=hours, catchup_hours=catchup_hours,
        catchup_min_score=catchup_min_score, min_score=min_score,
        max_stories=max_stories, on_date=on_date, exclude_urls=exclude,
    )
    if not pairs:
        log.info("Newsletter: no qualifying stories, skipping")
        return None

    stories = [_story_entry(p, r) for p, r in pairs]

    # Intro paragraph — the editorial morning brief over today's primaries.
    try:
        intro = generate_morning_brief(
            client, [p for p, _ in pairs], model=brief_model, max_stories=max_stories
        ) or ""
    except Exception as exc:  # noqa: BLE001
        log.warning("Newsletter intro generation failed (non-fatal): %s", exc)
        intro = ""

    issue_date = on_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Link the day's episode + borrow its title for the subject, if rendered.
    video_title = None
    video_url = None
    script_path = scripts_dir / f"{issue_date}.json"
    if script_path.exists():
        try:
            video_title = json.loads(script_path.read_text(encoding="utf-8")).get("title")
        except (json.JSONDecodeError, OSError):
            pass
    if (Path(newsletter_dir).parent / "videos" / f"{issue_date}.mp4").exists():
        video_url = f"{site_url}/videos/{issue_date}.mp4"

    return {
        "issue_date": issue_date,
        "subject": _subject_line(stories, video_title, issue_date),
        "intro": intro,
        "video_url": video_url,
        "site_url": site_url,
        "stories": stories,
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "story_count": len(stories),
            "story_urls": [s["url"] for s in stories],
        },
    }


def write_newsletter_json(newsletter: dict, newsletter_dir: Path) -> Path:
    """Persist the issue (for the dedup archive and re-rendering)."""
    newsletter_dir.mkdir(parents=True, exist_ok=True)
    path = newsletter_dir / f"{newsletter['issue_date']}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(newsletter, f, indent=2, ensure_ascii=False)
    return path
