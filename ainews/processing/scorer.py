import json
import re
from typing import Optional

import anthropic

from ainews.models import RawNewsItem, ProcessedNewsItem


DEFAULT_SCORING_PROMPT = """\
You are an AI news analyst for an educational video production company.
We create educational videos that teach audiences about AI developments,
how new tools work, and what they mean for the industry.

Analyze EACH of the following news items and provide for each.
When "Article Content" is provided, use it for accurate, in-depth analysis.

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
4. A category — one of: "New Releases", "Research", "Business", or "Developer Tools"
   - "New Releases": New model launches, new product releases, new tool announcements, new API versions, new open-source releases
   - "Research": Research papers, benchmarks, technical analyses, academic publications, novel techniques
   - "Business": Partnerships, funding rounds, acquisitions, hiring, policy, regulation, market analysis, corporate strategy
   - "Developer Tools": SDKs, frameworks, libraries, developer platforms, tutorials, infrastructure, API updates, tooling

Score guide:
- 9-10: Industry-shaping (major model release, breakthrough, major policy) with high educational value
- 7-8: Very important (significant update, notable partnership, key research) with good teaching potential
- 5-6: Moderate (useful update, interesting but not groundbreaking)
- 3-4: Minor (small update, niche interest, low educational value)
- 1-2: Low relevance (routine, not newsworthy for educational video)

Respond in valid JSON only — a JSON array with one object per item, in the same order as the input.
Each object must have: {"id": N, "summary": "...", "score": N, "reasoning": "...", "learning_objectives": ["...", "...", "..."], "category": "New Releases" or "Research" or "Business" or "Developer Tools"}

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
    categories: list[str] | None = None,
    content_max: int = 3000,
) -> list[ProcessedNewsItem]:
    """Score a batch of items in a single API call."""
    items_text = "\n\n".join(
        _format_item_for_batch(start_index + i, item, content_max) for i, item in enumerate(items)
    )
    prompt = scoring_prompt.replace("{items_text}", items_text)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=800 * len(items),
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
                published=item.published, content=item.content,
                summary=item.description or "",
                score=5, score_reasoning=f"Auto-scored (API error: {e})",
                category=(categories[-1] if categories else "Developer Tools"),
                fetched_via=item.fetched_via,
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
        valid_categories = set(categories) if categories else {"New Releases", "Research", "Business", "Developer Tools"}
        fallback_category = categories[-1] if categories else "Developer Tools"
        category = data.get("category", fallback_category)
        if category not in valid_categories:
            category = fallback_category

        print(f"  [Scorer]   Item {start_index + i}: {score}/10 | {category} | {item.title[:50]}")

        processed.append(ProcessedNewsItem(
            title=item.title, url=item.url, source=item.source,
            published=item.published, content=item.content,
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
    categories: list[str] | None = None,
    content_max: int = 3000,
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
        batch_results = _score_batch(client, model, batch, start + 1, prompt, categories, content_max)
        processed.extend(batch_results)

    return processed
