"""Video script generator — turns the day's top stories into a narrated episode script.

Stage 1 of the daily video pipeline. Selects the highest-scoring story groups
from the last 24 hours and asks Claude for a structured episode script:

- **cold_open** — a hook that earns the next five minutes
- **segments** — one per story, each with an on-screen headline and narration
- **sign_off** — a short outro

The script targets a fixed runtime (default 5 minutes at ~155 spoken words per
minute) and the generator enforces the word budget: if the first draft lands
outside ±12% of target, it asks Claude for one revision pass.

Tone is entertaining and slightly irreverent — the prompt aims the snark at
industry hype, never at people, and forbids inventing facts not present in the
source summaries.

Output is a JSON file (consumed by the TTS/render stages) plus a human-readable
Markdown twin, written to ``data/video_scripts/<date>.{json,md}``.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import anthropic

from ainews.models import ProcessedNewsItem
from ainews.storage.database import Database


DEFAULT_SCRIPT_MODEL = "claude-sonnet-4-6"

# Conversational narration pace. 155 wpm is a comfortable "energetic host"
# read; the renderer can trim silence either way.
DEFAULT_WORDS_PER_MINUTE = 155

# Accept drafts within this fraction of the word target before asking for a
# revision (one revision max — bounded cost beats a perfect word count).
WORD_TOLERANCE = 0.12

_SCRIPT_PROMPT = """\
You are the head writer for "{show_name}", a daily AI-news video. One host,
direct to camera, five minutes. The audience is smart and tech-curious but
not in the weeds — they watch because the show is FUN first and informative
a very close second.

Voice and tone:
- Entertaining and slightly irreverent. The snark is aimed at industry hype,
  breathless press releases, and the general absurdity of the AI news cycle —
  never at individual people, and never at the audience.
- Confident, punchy sentences written for the EAR, not the page. Contractions
  always. No corporate filler, no "in today's fast-paced world".
- Wit comes from observation and timing, not forced puns. One good aside per
  segment beats three weak ones.
- The facts stay straight. Use ONLY information in the story notes below.
  If a detail isn't in the notes, the host doesn't say it. Numbers and names
  must match the notes exactly.
- No emojis, no stage directions, no [pause] markers — narration text only.
- Transitions between stories should feel like one person talking, not a
  slide deck ("Speaking of money on fire...", "Meanwhile, over at...").

Episode structure — respond with VALID JSON ONLY, exactly this shape:
{{
  "title": "episode title, max 9 words, punchy, no date",
  "cold_open": "~{cold_open_words} words. Hook the viewer with the biggest or
                funniest thing in today's lineup, then promise the rest.",
  "segments": [
    {{
      "slug": "kebab-case-id-from-story",
      "headline": "on-screen headline, max 8 words",
      "source": "primary source name, copied from the notes",
      "url": "primary story URL, copied from the notes",
      "narration": "~{segment_words} words of narration for this story",
      "bullets": [
        {{
          "text": "on-screen bullet, max 8 words, a key fact",
          "anchor": "VERBATIM 2-4 word phrase copied exactly from this segment's narration"
        }}
      ]
    }}
  ],
  "sign_off": "~{sign_off_words} words. Land one last laugh and sign off."
}}

Hard requirements:
- Exactly {n_stories} segments, in the order that makes the best SHOW (you may
  reorder; lead with your strongest material, end on the second-strongest).
- Total narration (cold_open + all segment narration + sign_off) must be
  {target_words} words, within about 10%. Count as you go.
- Every segment's "source" and "url" must be copied verbatim from its story
  notes.
- Each segment has 3-4 bullets — the on-screen slideshow supporting the
  narration. Bullets are punchy facts (numbers, names, the "so what"), not
  full sentences. Each bullet's "anchor" must be a SHORT phrase copied
  character-for-character from that segment's narration, taken from the
  moment the narration covers that bullet's content, in narration order —
  the bullet appears on screen when the host says the anchor.

Today's story notes:
{stories_block}
"""

_REVISION_PROMPT = """\
Your draft's total narration is {actual_words} words; the target is
{target_words} (must land within about 10%). {direction}

Return the COMPLETE corrected script as valid JSON in exactly the same shape
as before — do not drop segments, do not change "source" or "url" fields, and
keep the same tone. JSON only.
"""


def _format_story_block(
    index: int,
    primary: ProcessedNewsItem,
    related: list,
    summary_max: int = 700,
) -> str:
    """Format one story group as notes for the prompt."""
    summary = (primary.summary or "").strip().replace("\n", " ")
    if len(summary) > summary_max:
        summary = summary[:summary_max].rsplit(" ", 1)[0] + "…"
    lines = [
        f"[Story {index}]",
        f"Title: {primary.title}",
        f"Source: {primary.source}",
        f"URL: {primary.url}",
        f"Category: {primary.category} | Impact score: {primary.score}/10",
        f"Summary: {summary}",
    ]
    if related:
        others = ", ".join(sorted({r.source for r in related if r.source}))
        if others:
            lines.append(f"Also covered by: {others}")
    return "\n".join(lines)


def count_narration_words(script: dict) -> int:
    """Total spoken words: cold open + every segment narration + sign-off."""
    parts = [script.get("cold_open", ""), script.get("sign_off", "")]
    parts.extend(seg.get("narration", "") for seg in script.get("segments", []))
    return sum(len(p.split()) for p in parts if p)


def _parse_script_json(text: str) -> dict:
    """Extract the JSON object from a model response (tolerates ``` fences)."""
    text = text.strip()
    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if json_match:
        text = json_match.group()
    script = json.loads(text)
    if not isinstance(script, dict):
        raise ValueError(f"Expected JSON object, got {type(script).__name__}")
    return script


def _validate_script(script: dict, n_stories: int) -> None:
    """Raise ValueError if the script is structurally unusable downstream."""
    for key in ("title", "cold_open", "segments", "sign_off"):
        if not script.get(key):
            raise ValueError(f"Script missing required field: {key}")
    segments = script["segments"]
    if not isinstance(segments, list) or len(segments) != n_stories:
        raise ValueError(
            f"Expected {n_stories} segments, got "
            f"{len(segments) if isinstance(segments, list) else type(segments).__name__}"
        )
    for i, seg in enumerate(segments):
        for key in ("headline", "narration", "source", "url"):
            if not seg.get(key):
                raise ValueError(f"Segment {i + 1} missing required field: {key}")
        bullets = seg.get("bullets") or []
        if not isinstance(bullets, list) or not (2 <= len(bullets) <= 5):
            raise ValueError(f"Segment {i + 1} needs 2-5 bullets, got {len(bullets)}")
        for j, bullet in enumerate(bullets):
            if not bullet.get("text") or not bullet.get("anchor"):
                raise ValueError(
                    f"Segment {i + 1} bullet {j + 1} missing text or anchor"
                )


def previously_covered_urls(scripts_dir: Path, days: int = 14) -> "set[str]":
    """URLs already used by recent episodes (so stories never repeat).

    Reads the ``meta.story_urls`` of every episode script in the window.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    covered: "set[str]" = set()
    if not scripts_dir.exists():
        return covered
    for path in scripts_dir.glob("*.json"):
        if path.stem < cutoff:
            continue
        try:
            with open(path, encoding="utf-8") as f:
                covered.update(json.load(f).get("meta", {}).get("story_urls", []))
        except (json.JSONDecodeError, OSError):
            continue
    return covered


def select_stories(
    db: Database,
    *,
    hours: int = 72,
    min_score: int = 6,
    max_stories: int = 7,
    now: Optional[datetime] = None,
    on_date: Optional[str] = None,
    exclude_urls: "Optional[set[str]]" = None,
) -> list:
    """Pick the top story groups as (primary, [related]) pairs.

    Default window is a 72h lookback — wide enough that a major story
    published just before yesterday's episode cutoff still gets picked up —
    combined with ``exclude_urls`` (stories covered by earlier episodes) so
    nothing repeats. ``on_date`` switches to an exact UTC calendar day
    instead, for regenerating a specific date's episode.

    Includes acknowledged items — a story the user already triaged is still
    news to the video audience.
    """
    if on_date:
        start = datetime.fromisoformat(on_date).replace(tzinfo=timezone.utc)
        end: Optional[datetime] = start + timedelta(days=1)
    else:
        now = now or datetime.now(timezone.utc)
        start = now - timedelta(hours=hours)
        end = None
    pairs = db.query_grouped(
        min_score=min_score,
        start_date=start,
        end_date=end,
        show_acknowledged=True,
        sort_by="score",
        sort_dir="DESC",
        limit=100,
    )
    if exclude_urls:
        pairs = [
            (primary, related) for primary, related in pairs
            if primary.url not in exclude_urls
            and not any(r.url in exclude_urls for r in related)
        ]
    return pairs[:max_stories]


def generate_script(
    client: anthropic.Anthropic,
    stories: list,
    *,
    model: str = DEFAULT_SCRIPT_MODEL,
    target_minutes: float = 5.0,
    words_per_minute: int = DEFAULT_WORDS_PER_MINUTE,
    show_name: str = "The Daily Prompt",
    logger: Optional[logging.Logger] = None,
) -> dict:
    """Generate the episode script for the given (primary, [related]) pairs.

    Returns the script dict with a ``meta`` key added. Raises on empty input,
    unparseable responses, or structurally invalid scripts.
    """
    log = logger or logging.getLogger(__name__)
    if not stories:
        raise ValueError("No stories to script")

    n_stories = len(stories)
    target_words = round(target_minutes * words_per_minute)
    cold_open_words = 70
    sign_off_words = 45
    segment_words = max(60, (target_words - cold_open_words - sign_off_words) // n_stories)

    stories_block = "\n\n".join(
        _format_story_block(i + 1, primary, related)
        for i, (primary, related) in enumerate(stories)
    )
    prompt = _SCRIPT_PROMPT.format(
        show_name=show_name,
        n_stories=n_stories,
        target_words=target_words,
        cold_open_words=cold_open_words,
        segment_words=segment_words,
        sign_off_words=sign_off_words,
        stories_block=stories_block,
    )

    messages = [{"role": "user", "content": prompt}]
    response = client.messages.create(model=model, max_tokens=4000, messages=messages)
    text = response.content[0].text
    script = _parse_script_json(text)
    _validate_script(script, n_stories)

    # One revision pass if the word count is out of band.
    actual = count_narration_words(script)
    low = round(target_words * (1 - WORD_TOLERANCE))
    high = round(target_words * (1 + WORD_TOLERANCE))
    if not low <= actual <= high:
        direction = (
            "Trim it — tighten every section proportionally; cut the weakest jokes first."
            if actual > high
            else "Expand it — add substance and one more good aside per segment, not padding."
        )
        log.info(
            "Script draft is %d words (target %d±%d%%), requesting revision",
            actual, target_words, int(WORD_TOLERANCE * 100),
        )
        messages.append({"role": "assistant", "content": text})
        messages.append({
            "role": "user",
            "content": _REVISION_PROMPT.format(
                actual_words=actual, target_words=target_words, direction=direction
            ),
        })
        response = client.messages.create(model=model, max_tokens=4000, messages=messages)
        revised = _parse_script_json(response.content[0].text)
        try:
            _validate_script(revised, n_stories)
            script = revised
            actual = count_narration_words(script)
        except ValueError as exc:
            # A structurally broken revision is worse than an off-length draft.
            log.warning("Revision was invalid (%s); keeping first draft", exc)

    script["meta"] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "target_minutes": target_minutes,
        "words_per_minute": words_per_minute,
        "target_words": target_words,
        "narration_words": actual,
        "estimated_runtime_seconds": round(actual / words_per_minute * 60),
        "story_count": n_stories,
        "story_urls": [primary.url for primary, _related in stories],
    }
    return script


def render_markdown(script: dict, day_key: str) -> str:
    """Human-readable twin of the JSON script, for review in an editor."""
    meta = script.get("meta", {})
    runtime = meta.get("estimated_runtime_seconds", 0)
    lines = [
        f"# {script['title']}",
        "",
        f"*Episode for {day_key} — {meta.get('narration_words', '?')} words, "
        f"~{runtime // 60}:{runtime % 60:02d} runtime*",
        "",
        "## Cold open",
        "",
        script["cold_open"],
        "",
    ]
    for i, seg in enumerate(script["segments"], 1):
        lines += [
            f"## Segment {i}: {seg['headline']}",
            "",
            f"*{seg['source']} — {seg['url']}*",
            "",
            seg["narration"],
            "",
        ]
    lines += ["## Sign-off", "", script["sign_off"], ""]
    return "\n".join(lines)


def write_script_files(script: dict, output_dir: Path, day_key: str) -> "tuple[Path, Path]":
    """Write <day>.json and <day>.md; returns both paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{day_key}.json"
    md_path = output_dir / f"{day_key}.md"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(script, f, indent=2, ensure_ascii=False)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_markdown(script, day_key))
    return json_path, md_path


def run_video_script(
    db: Database,
    client: anthropic.Anthropic,
    *,
    output_dir: Path,
    hours: int = 72,
    min_score: int = 6,
    max_stories: int = 7,
    target_minutes: float = 5.0,
    words_per_minute: int = DEFAULT_WORDS_PER_MINUTE,
    model: str = DEFAULT_SCRIPT_MODEL,
    show_name: str = "The Daily Prompt",
    on_date: Optional[str] = None,
    exclude_covered: bool = True,
    logger: Optional[logging.Logger] = None,
) -> dict:
    """End-to-end Stage 1: select stories, generate, persist.

    Returns ``{"status": "ok", "json_path": ..., "md_path": ..., ...}`` or
    ``{"status": "no-stories"}`` when the window has nothing scriptworthy.
    """
    log = logger or logging.getLogger(__name__)
    exclude_urls = previously_covered_urls(output_dir) if exclude_covered else set()
    if exclude_urls:
        log.info("Video script: excluding %d previously covered stories", len(exclude_urls))
    stories = select_stories(
        db, hours=hours, min_score=min_score, max_stories=max_stories,
        on_date=on_date, exclude_urls=exclude_urls,
    )
    if not stories:
        log.info(
            "Video script: no uncovered stories with score >= %d in the window, skipping",
            min_score,
        )
        return {"status": "no-stories"}

    log.info(
        "Video script: %d stories selected (top score %d)",
        len(stories), stories[0][0].score,
    )
    script = generate_script(
        client, stories,
        model=model, target_minutes=target_minutes,
        words_per_minute=words_per_minute, show_name=show_name, logger=log,
    )
    day_key = on_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    json_path, md_path = write_script_files(script, output_dir, day_key)
    log.info(
        "Video script written: %s (%d words, ~%ds)",
        json_path, script["meta"]["narration_words"],
        script["meta"]["estimated_runtime_seconds"],
    )
    return {
        "status": "ok",
        "json_path": str(json_path),
        "md_path": str(md_path),
        "narration_words": script["meta"]["narration_words"],
        "estimated_runtime_seconds": script["meta"]["estimated_runtime_seconds"],
        "story_count": script["meta"]["story_count"],
    }
