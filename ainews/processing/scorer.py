import json
import re
from datetime import datetime, timezone
from typing import Optional

import anthropic

from ainews import llm
from ainews.models import RawNewsItem, ProcessedNewsItem

# Room for adaptive thinking plus ~10 scored items (the newer tokenizer counts
# ~30% more tokens for the same text). Non-streaming, so kept at 16K.
SCORING_MAX_TOKENS = 16000

# Reasoning written when Claude couldn't score an item (API error, or the
# item missing from the response). Such rows are stored so the story isn't
# lost, then re-scored on later runs by rescore_fallback_items.
FALLBACK_REASON_PREFIX = "Auto-scored ("


def needs_rescore(reasoning: str) -> bool:
    return (reasoning or "").startswith(FALLBACK_REASON_PREFIX)


DEFAULT_SCORING_PROMPT = """\
You are the news editor for a daily AI news show. Your job is to judge
each item's NEWSWORTHINESS: how much it matters to people who follow AI —
its impact, importance, and urgency — and to brief the host accurately.

Analyze EACH of the following news items and provide for each.
When "Article Content" is provided, use it for accurate, in-depth analysis.

1. A short summary (2-3 sentences) — the dek shown next to the headline in
   the triage list. It must be standalone and self-contained: what happened,
   the single most important detail, and why a reader should care. No
   preamble, no bullets, no restating the title.
2. A detailed summary (4-6 sentences) — the long copy shown in the reading
   pane. It should:
   - Lead with what happened: who did what, with the concrete specifics
     (numbers, names, dates) that make it news
   - Explain why it matters: who is affected and what changes
   - For new releases: what's new, how it compares to what existed, and
     whether it's available now
   - For industry news: the strategic implications and broader context
   - Use clear, accessible language; no hype, no press-release framing
3. A newsworthiness score from 1-10 based on:
   - Impact: how many people, companies, or workflows does this affect?
   - Importance: does this change the direction of the AI industry?
   - Novelty: genuinely new development vs. incremental update or rehash
   - Credibility: confirmed/official news scores above rumor and speculation
   - Urgency: is this the kind of thing people expect to hear about today?
4. Key takeaways (3-5 bullet points): the facts and implications a viewer
   should remember. Each bullet concise and concrete.
5. A category — one of: "New Releases", "Research", "Business", or "Developer Tools"
   - "New Releases": New model launches, new product releases, new tool announcements, new API versions, new open-source releases
   - "Research": Research papers, benchmarks, technical analyses, academic publications, novel techniques
   - "Business": Partnerships, funding rounds, acquisitions, hiring, policy, regulation, market analysis, corporate strategy
   - "Developer Tools": SDKs, frameworks, libraries, developer platforms, tutorials, infrastructure, API updates, tooling

Score guide:
- 9-10: Industry-shaping — major model releases, landmark policy/regulation,
        major acquisitions or breakthroughs everyone in AI will be talking about
- 7-8:  Significant — important launches, notable research, big partnerships;
        clearly belongs in today's news rundown
- 5-6:  Moderate — real news but incremental; include only on a slow day
- 3-4:  Minor — small updates, niche interest, weak sourcing
- 1-2:  Noise — routine, promotional, or not really news

Respond in valid JSON only — a JSON array with one object per item, in the same order as the input.
Each object must have: {"id": N, "short_summary": "...", "summary": "...", "score": N, "score_rationale": "...", "learning_objectives": ["key takeaway", "...", "..."], "category": "New Releases" or "Research" or "Business" or "Developer Tools"}
("score_rationale" is one sentence telling the editor why the item earned its score. The "learning_objectives" key carries the key-takeaway bullets; the field name is kept for storage compatibility.)

NEWS ITEMS:
{items_text}
"""


def _format_item_for_batch(index: int, item: RawNewsItem, content_max: int = 3000) -> str:
    """Format a single item for inclusion in a batch prompt."""
    desc = item.description or "(no description available)"
    parts = [f"[Item {index}]", f"Title: {item.title}", f"Source: {item.source}", f"Description: {desc}"]
    if item.content:
        parts.append(f"Article Content: {item.content[:content_max]}")
    return "\n".join(parts)


def _score_batch(
    client: anthropic.Anthropic, model: str, items: list[RawNewsItem],
    start_index: int, scoring_prompt: str,
    categories: Optional[list[str]] = None,
    content_max: int = 3000,
    effort: str = llm.DEFAULT_EFFORT["scoring"],
) -> list[ProcessedNewsItem]:
    """Score a batch of items in a single API call."""
    items_text = "\n\n".join(
        _format_item_for_batch(start_index + i, item, content_max) for i, item in enumerate(items)
    )
    prompt = scoring_prompt.replace("{items_text}", items_text)

    try:
        text = llm.complete(
            client, model=model, effort=effort, prompt=prompt,
            max_tokens=SCORING_MAX_TOKENS,
        ).strip()
        # Extract JSON array from response
        json_match = re.search(r"\[.*\]", text, re.DOTALL)
        if json_match:
            results = json.loads(json_match.group())
        else:
            results = json.loads(text)

        # Validate batch length
        if not isinstance(results, list):
            print(f"    [Scorer] Warning: Expected JSON array, got {type(results).__name__}. Using fallback scoring.")
            results = []
        elif len(results) != len(items):
            print(f"    [Scorer] Warning: Expected {len(items)} results, got {len(results)}. Using fallback for missing items.")
    except Exception as e:
        print(f"    [Scorer] Batch API error: {e}")
        return [
            ProcessedNewsItem(
                title=item.title, url=item.url, source=item.source,
                published=item.published, content=item.content,
                summary=item.description or "",
                score=5, score_reasoning=f"{FALLBACK_REASON_PREFIX}API error: {e})",
                category=(categories[-1] if categories else "Developer Tools"),
                fetched_via=item.fetched_via,
            )
            for item in items
        ]

    # Match results to items by the "id" the prompt asks for; position is only
    # a fallback, since one skipped item would shift every later result. If
    # no id falls in this batch's range (the model renumbered from 1), the
    # ids are meaningless here and position is all we have.
    batch_ids = range(start_index, start_index + len(items))
    by_id = {
        r["id"]: r for r in results
        if isinstance(r, dict) and isinstance(r.get("id"), int)
    }
    if not any(i in by_id for i in batch_ids):
        by_id = {}

    processed = []
    for i, item in enumerate(items):
        if by_id:
            data = by_id.get(start_index + i)
        else:
            data = results[i] if i < len(results) else None

        if not isinstance(data, dict) or not data:
            print(f"  [Scorer]   Item {start_index + i}: missing from response, will rescore")
            processed.append(ProcessedNewsItem(
                title=item.title, url=item.url, source=item.source,
                published=item.published, content=item.content,
                summary=item.description or "",
                score=5, score_reasoning=f"{FALLBACK_REASON_PREFIX}missing from model response)",
                category=(categories[-1] if categories else "Developer Tools"),
                fetched_via=item.fetched_via,
            ))
            continue

        score = max(1, min(10, int(data.get("score", 5))))
        summary = data.get("summary", item.description or "")
        short_summary = data.get("short_summary", "") or ""
        # "reasoning" is what older (and custom config) prompts asked for.
        reasoning = data.get("score_rationale") or data.get("reasoning", "")
        raw_objectives = data.get("learning_objectives", [])
        if isinstance(raw_objectives, list):
            learning_objectives = "\n".join(f"- {obj}" for obj in raw_objectives if obj)
        else:
            learning_objectives = str(raw_objectives)
        valid_categories = set(categories) if categories else {"New Releases", "Research", "Business", "Developer Tools"}
        fallback_category = categories[-1] if categories else "Developer Tools"
        category = data.get("category", fallback_category)
        if category not in valid_categories:
            category = fallback_category

        print(f"  [Scorer]   Item {start_index + i}: {score}/10 | {category} | {item.title[:50]}")

        processed.append(ProcessedNewsItem(
            title=item.title, url=item.url, source=item.source,
            published=item.published, content=item.content,
            summary=summary, short_summary=short_summary,
            score=score, score_reasoning=reasoning,
            learning_objectives=learning_objectives,
            category=category, fetched_via=item.fetched_via,
        ))
    return processed


def score_items(
    client: anthropic.Anthropic,
    model: str,
    items: list[RawNewsItem],
    batch_size: int = 10,
    scoring_prompt: Optional[str] = None,
    categories: Optional[list[str]] = None,
    content_max: int = 3000,
    effort: str = llm.DEFAULT_EFFORT["scoring"],
) -> list[ProcessedNewsItem]:
    """Score a list of raw news items using Claude in batches."""
    batch_size = max(1, batch_size)
    prompt = scoring_prompt or DEFAULT_SCORING_PROMPT
    processed = []
    total = len(items)
    num_batches = (total + batch_size - 1) // batch_size

    for batch_num in range(num_batches):
        start = batch_num * batch_size
        end = min(start + batch_size, total)
        batch = items[start:end]
        print(f"  [Scorer] Scoring batch {batch_num + 1}/{num_batches} (items {start + 1}-{end} of {total})...")
        batch_results = _score_batch(
            client, model, batch, start + 1, prompt, categories, content_max, effort
        )
        processed.extend(batch_results)

    return processed


def rescore_fallback_items(
    db,
    client: anthropic.Anthropic,
    model: str,
    *,
    batch_size: int = 10,
    scoring_prompt: Optional[str] = None,
    categories: Optional[list[str]] = None,
    content_max: int = 3000,
    max_age_days: int = 7,
    limit: int = 50,
    now: Optional[datetime] = None,
    effort: str = llm.DEFAULT_EFFORT["scoring"],
) -> int:
    """Re-score recent rows stored with a fallback score. Returns rows fixed.

    Rows that fail again keep their fallback marker and back off
    exponentially (15 min, 30 min, 1 h, ... up to a day) until they age out
    of ``max_age_days`` — so an item the model keeps rejecting isn't paid
    for on every 15-minute run.
    """
    now = now or datetime.now(timezone.utc)
    rows = db.get_items_needing_rescore(
        prefix=FALLBACK_REASON_PREFIX, max_age_days=max_age_days, limit=limit, now=now
    )
    if not rows:
        return 0
    print(f"  [Scorer] Re-scoring {len(rows)} items that previously failed to score...")
    raws = [
        RawNewsItem(
            title=r.title, url=r.url, source=r.source, published=r.published,
            description=r.summary, content=r.content, fetched_via=r.fetched_via,
        )
        for r in rows
    ]
    results = score_items(
        client, model, raws, batch_size=batch_size, scoring_prompt=scoring_prompt,
        categories=categories, content_max=content_max, effort=effort,
    )
    fixed = 0
    for row, result in zip(rows, results):
        if needs_rescore(result.score_reasoning):
            db.defer_rescore(row.id, now)
            continue
        db.update_scoring(row.id, result)
        fixed += 1
    return fixed
