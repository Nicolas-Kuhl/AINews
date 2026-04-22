"""Brief generator — turns the day's scored stories into an editorial paragraph.

Produces two kinds of briefs:

- **Morning Brief** — a wide-lens paragraph covering today's stories, written in
  the handoff's editorial voice. Persisted to ``morning_briefs``.
- **Day Brief** — a per-date paragraph rendered under each day header in the
  Digest view. Persisted to ``day_briefs``.

The generator calls Claude Sonnet (cost-optimized vs. Opus) and asks for a
single paragraph with ``**bold**`` markdown for entities/numbers.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional

import anthropic

from ainews.models import ProcessedNewsItem
from ainews.storage.database import Database


DEFAULT_BRIEF_MODEL = "claude-sonnet-4-6"

_MORNING_PROMPT = """\
You are an editor writing the Morning Brief for an AI-news triage console.

Output format: a SINGLE paragraph of 3–5 sentences (no lists, no headers),
roughly 110–160 words. Use **bold** markdown around model names, company
names, and key numbers. Lead with the highest-signal story. Close with one
quieter pickup worth a read. Do not restate the date or say "today". Do not
start with a kicker — just the paragraph.

Stories (score · source · title · one-line summary):
{stories_block}
"""

_DAY_PROMPT = """\
You are an editor writing a Day Brief paragraph for an AI-news triage console.

Output format: a SINGLE paragraph of 3–5 sentences (no lists, no headers),
roughly 90–140 words. Use **bold** markdown around model names, company names,
and key numbers. Lead with the highest-signal story. Do not mention the date,
do not say "today" or "yesterday". Do not start with a kicker.

Stories (score · source · title · one-line summary):
{stories_block}
"""


def _format_story_line(item: ProcessedNewsItem) -> str:
    summary = (item.summary or "").strip().replace("\n", " ")
    if len(summary) > 280:
        summary = summary[:280].rsplit(" ", 1)[0] + "…"
    return f"- score {item.score} · {item.source} · {item.title} · {summary}"


def _call_claude(
    client: anthropic.Anthropic, model: str, prompt: str
) -> str:
    response = client.messages.create(
        model=model,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text.strip()
    # Strip any leading "Morning Brief:" / "Day Brief:" prefix the model might add
    for prefix in ("Morning Brief:", "Day Brief:", "Brief:"):
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix):].strip()
    return text


def generate_morning_brief(
    client: anthropic.Anthropic,
    stories: Iterable[ProcessedNewsItem],
    *,
    model: str = DEFAULT_BRIEF_MODEL,
    max_stories: int = 20,
) -> Optional[str]:
    ordered = sorted(stories, key=lambda s: s.score, reverse=True)[:max_stories]
    if not ordered:
        return None
    block = "\n".join(_format_story_line(s) for s in ordered)
    prompt = _MORNING_PROMPT.format(stories_block=block)
    return _call_claude(client, model, prompt)


def generate_day_brief(
    client: anthropic.Anthropic,
    stories: Iterable[ProcessedNewsItem],
    *,
    model: str = DEFAULT_BRIEF_MODEL,
    max_stories: int = 15,
) -> Optional[str]:
    ordered = sorted(stories, key=lambda s: s.score, reverse=True)[:max_stories]
    if not ordered:
        return None
    block = "\n".join(_format_story_line(s) for s in ordered)
    prompt = _DAY_PROMPT.format(stories_block=block)
    return _call_claude(client, model, prompt)


def _stories_for_day(db: Database, day_key: str) -> list[ProcessedNewsItem]:
    by_day = db.query_by_day(
        min_score=1, max_score=10, show_acknowledged=True, limit_days=365
    )
    groups = by_day.get(day_key) or []
    # One entry per group (primary only) — matches what the Digest shows
    return [primary for primary, _related in groups]


def refresh_briefs(
    db: Database,
    client: anthropic.Anthropic,
    *,
    today: Optional[date] = None,
    lookback_days: int = 5,
    model: str = DEFAULT_BRIEF_MODEL,
    force: bool = False,
    logger: Optional[logging.Logger] = None,
) -> dict:
    """Regenerate the Morning Brief for today plus Day Briefs for the last N days.

    Returns a summary dict: ``{"morning": "ok"|"skipped"|"error", "days": {...}}``.
    """
    log = logger or logging.getLogger(__name__)
    today = today or datetime.now(timezone.utc).date()
    result: dict = {"morning": "skipped", "days": {}}

    # Morning Brief for today — always regenerate because new stories keep
    # arriving during the day; caching only makes sense for historical days.
    today_key = today.isoformat()
    stories = _stories_for_day(db, today_key)
    if stories:
        try:
            paragraph = generate_morning_brief(client, stories, model=model)
            if paragraph:
                db.upsert_morning_brief(today_key, paragraph=paragraph)
                result["morning"] = "ok"
                log.info("Morning Brief written for %s (%d stories)", today_key, len(stories))
        except Exception as exc:  # noqa: BLE001
            log.warning("Morning Brief generation failed for %s: %s", today_key, exc)
            result["morning"] = f"error: {exc}"
    else:
        log.info("Morning Brief: no stories for %s, skipping", today_key)

    # Day Briefs for the last `lookback_days` days. Today is always regenerated
    # (live data); older days use cache unless --force.
    for offset in range(lookback_days):
        day = today - timedelta(days=offset)
        day_key = day.isoformat()
        is_today = offset == 0
        existing = db.get_day_briefs([day_key]).get(day_key)
        if existing and not force and not is_today:
            result["days"][day_key] = "cached"
            continue
        stories = _stories_for_day(db, day_key)
        if not stories:
            result["days"][day_key] = "no-stories"
            continue
        try:
            paragraph = generate_day_brief(client, stories, model=model)
            if paragraph:
                db.upsert_day_brief(day_key, paragraph)
                result["days"][day_key] = "ok"
                log.info("Day Brief written for %s (%d stories)", day_key, len(stories))
            else:
                result["days"][day_key] = "empty"
        except Exception as exc:  # noqa: BLE001
            log.warning("Day Brief generation failed for %s: %s", day_key, exc)
            result["days"][day_key] = f"error: {exc}"

    return result
