import json
import re
from typing import Optional

import anthropic

from ainews.models import RawNewsItem, ProcessedNewsItem


DEFAULT_SCORING_PROMPT = """\
You are an AI news analyst for an educational video production company.
We create educational videos that teach audiences about AI developments,
how new tools work, and what they mean for the industry.

Analyze EACH of the following news items and provide for each:
1. A detailed summary (4-6 sentences) that:
   - Explains what happened and why it matters
   - Highlights the educational angle: what can viewers learn from this?
   - For new releases: explain what's new, what it can do, and why it's important
   - For industry news: explain the industry implications and broader context
   - Uses clear, accessible language suitable for a general audience
2. An impact score from 1-10 based on:
   - Educational value: Can we teach something meaningful from this?
   - Teaching potential: How well does this translate to visual, engaging content?
   - Significance to the AI industry (new models, breakthroughs = higher)
   - Public interest / viral potential
   - Novelty (truly new vs. incremental update)
3. Learning objectives (3-5 bullet points): what a course covering this topic should teach.
   Each bullet should be a concise, actionable learning objective starting with a verb.
4. A category: either "New Releases" or "Industry"
   - "New Releases": New model launches, new product releases, new tool announcements, new API versions, new open-source releases
   - "Industry": Partnerships, research papers, policy, funding, analysis, opinions, updates to existing products

Score guide:
- 9-10: Industry-shaping (major model release, breakthrough, major policy) with high educational value
- 7-8: Very important (significant update, notable partnership, key research) with good teaching potential
- 5-6: Moderate (useful update, interesting but not groundbreaking)
- 3-4: Minor (small update, niche interest, low educational value)
- 1-2: Low relevance (routine, not newsworthy for educational video)

Respond in valid JSON only — a JSON array with one object per item, in the same order as the input.
Each object must have: {"id": N, "summary": "...", "score": N, "reasoning": "...", "learning_objectives": ["...", "...", "..."], "category": "New Releases" or "Industry"}

NEWS ITEMS:
{items_text}
"""


def _format_item_for_batch(index: int, item: RawNewsItem) -> str:
    """Format a single item for inclusion in a batch prompt."""
    desc = item.description or "(no description available)"
    return f"[Item {index}]\nTitle: {item.title}\nSource: {item.source}\nDescription: {desc}"


def _score_batch(
    client: anthropic.Anthropic, model: str, items: list[RawNewsItem],
    start_index: int, scoring_prompt: str,
) -> list[ProcessedNewsItem]:
    """Score a batch of items in a single API call."""
    items_text = "\n\n".join(
        _format_item_for_batch(start_index + i, item) for i, item in enumerate(items)
    )
    prompt = scoring_prompt.replace("{items_text}", items_text)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=600 * len(items),
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
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
                published=item.published,
                summary=item.description or "",
                score=5, score_reasoning=f"Auto-scored (API error: {e})",
                category="Industry", fetched_via=item.fetched_via,
            )
            for item in items
        ]

    processed = []
    for i, item in enumerate(items):
        try:
            data = results[i] if i < len(results) else {}
        except (IndexError, TypeError):
            data = {}

        score = max(1, min(10, int(data.get("score", 5))))
        summary = data.get("summary", item.description or "")
        reasoning = data.get("reasoning", "")
        raw_objectives = data.get("learning_objectives", [])
        if isinstance(raw_objectives, list):
            learning_objectives = "\n".join(f"- {obj}" for obj in raw_objectives if obj)
        else:
            learning_objectives = str(raw_objectives)
        category = data.get("category", "Industry")
        if category not in ("New Releases", "Industry"):
            category = "Industry"

        print(f"  [Scorer]   Item {start_index + i}: {score}/10 | {category} | {item.title[:50]}")

        processed.append(ProcessedNewsItem(
            title=item.title, url=item.url, source=item.source,
            published=item.published,
            summary=summary, score=score, score_reasoning=reasoning,
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
        batch_results = _score_batch(client, model, batch, start + 1, prompt)
        processed.extend(batch_results)

    return processed
