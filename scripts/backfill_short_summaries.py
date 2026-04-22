#!/usr/bin/env python3
"""Generate a short 2-3 sentence `short_summary` for every existing story
that does not yet have one.

Batches items into a single Claude call per batch to keep cost down. Call
``--dry-run`` to see how many rows would be processed without hitting the API.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

import anthropic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ainews.config import load_config  # noqa: E402
from ainews.storage.database import Database  # noqa: E402


DEFAULT_MODEL = "claude-sonnet-4-6"

PROMPT_TEMPLATE = """\
You are editing an AI-news triage console. For each item below, write a
SHORT summary (2-3 sentences, ~45-70 words) that will appear next to the
headline in a dense list. It must be standalone: what happened, the single
most important detail, and why a reader should care. Do not restate the
title. Do not start with a preamble. Plain prose, no bullets, no markdown.

Respond in valid JSON ONLY — a JSON array with one object per item in the
same order, each shaped as {"id": N, "short_summary": "..."}.

ITEMS:
{items_text}
"""


def _format_item(idx: int, row: dict) -> str:
    title = row["title"] or ""
    source = row["source"] or ""
    long_summary = (row["summary"] or "").strip()
    if len(long_summary) > 900:
        long_summary = long_summary[:900].rsplit(" ", 1)[0] + "…"
    parts = [f"[Item {idx}]", f"Title: {title}", f"Source: {source}"]
    if long_summary:
        parts.append(f"Long summary: {long_summary}")
    return "\n".join(parts)


def _run_batch(client: anthropic.Anthropic, model: str, rows: list[dict]) -> dict[int, str]:
    items_text = "\n\n".join(_format_item(i, r) for i, r in enumerate(rows))
    prompt = PROMPT_TEMPLATE.format(items_text=items_text)
    response = client.messages.create(
        model=model,
        max_tokens=250 * len(rows),
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text.strip()
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        data = json.loads(match.group())
    else:
        data = json.loads(text)
    result: dict[int, str] = {}
    for i, row in enumerate(rows):
        try:
            obj = data[i]
        except (IndexError, TypeError):
            continue
        short = (obj.get("short_summary") or "").strip()
        if short:
            result[row["id"]] = short
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--limit", type=int, default=None, help="Cap total rows processed")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--force", action="store_true", help="Regenerate even if short_summary is set")
    parser.add_argument("--dry-run", action="store_true", help="Count rows, no API calls")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("backfill")

    cfg = load_config()
    api_key = os.environ.get("ANTHROPIC_API_KEY") or cfg.get("anthropic_api_key")
    if not api_key and not args.dry_run:
        log.error("ANTHROPIC_API_KEY missing from env and config.yaml")
        return 1

    db = Database(cfg["db_path"])
    try:
        where = "" if args.force else "WHERE (short_summary IS NULL OR short_summary = '')"
        rows = list(
            db.conn.execute(
                f"SELECT id, title, source, summary FROM news_items {where} ORDER BY published DESC"
            ).fetchall()
        )
        rows = [dict(r) for r in rows]
        if args.limit is not None:
            rows = rows[: args.limit]

        log.info("Rows to process: %d (batch size %d)", len(rows), args.batch_size)
        if args.dry_run or not rows:
            return 0

        client = anthropic.Anthropic(api_key=api_key)
        total_written = 0
        total_failed = 0

        for start in range(0, len(rows), args.batch_size):
            batch = rows[start : start + args.batch_size]
            try:
                updates = _run_batch(client, args.model, batch)
            except Exception as exc:  # noqa: BLE001
                log.warning("Batch %d failed: %s", start // args.batch_size, exc)
                total_failed += len(batch)
                continue
            for item_id, short in updates.items():
                db.update_short_summary(item_id, short)
            total_written += len(updates)
            missing = len(batch) - len(updates)
            total_failed += missing
            log.info(
                "Batch %d: wrote %d/%d (cumulative %d written, %d failed)",
                start // args.batch_size + 1,
                len(updates),
                len(batch),
                total_written,
                total_failed,
            )
            # Gentle backoff between batches to avoid rate-limit spikes
            time.sleep(0.3)

        log.info("Done: %d written, %d failed", total_written, total_failed)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
