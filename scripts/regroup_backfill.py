#!/usr/bin/env python3
"""One-off backfill regroup using the tuned grouper + deep semantic dedup.

Default behavior:
  1. Drop pre-existing junk items (horoscopes, etc.) by marking them
     acknowledged=1 so they vanish from the triage console
  2. Rerun ``run_grouper`` with the new threshold/shared-words params
  3. Run ``deep_semantic_dedup`` across the full DB with a generous
     candidate cap

Estimated cost on the current production DB (~5,800 items): ~$0.50 in Sonnet
tokens, ~1 minute runtime.

Use ``--dry-run`` to print counts only.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import anthropic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ainews.config import load_config  # noqa: E402
from ainews.processing.content_filter import is_junk  # noqa: E402
from ainews.processing.grouper import deep_semantic_dedup, run_grouper  # noqa: E402
from ainews.storage.database import Database  # noqa: E402


def drop_existing_junk(db: Database, dry_run: bool = False) -> int:
    """Mark horoscope/zodiac/lifestyle items as acknowledged so they hide."""
    rows = db.conn.execute(
        "SELECT id, title FROM news_items WHERE acknowledged = 0"
    ).fetchall()
    affected = []
    for r in rows:
        # Build a fake RawNewsItem-ish object for is_junk
        from ainews.models import RawNewsItem
        item = RawNewsItem(title=r["title"], url="x", source="x")
        bad, reason = is_junk(item)
        if bad:
            affected.append((r["id"], r["title"][:60], reason))
    if not affected:
        return 0
    if dry_run:
        return len(affected)
    for item_id, _t, _r in affected:
        db.conn.execute(
            "UPDATE news_items SET acknowledged = 1 WHERE id = ?", (item_id,)
        )
    db.conn.commit()
    return len(affected)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Count only, no writes")
    parser.add_argument("--skip-junk", action="store_true", help="Skip the junk-cleanup pass")
    parser.add_argument("--skip-semantic", action="store_true", help="Skip deep_semantic_dedup")
    parser.add_argument("--max-candidates", type=int, default=1200, help="Cap on pairs sent to Claude")
    parser.add_argument("--model", default=None, help="Override Claude model (defaults to config)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("regroup_backfill")

    cfg = load_config()
    db = Database(cfg["db_path"])
    try:
        before_groups = db.conn.execute(
            "SELECT COUNT(DISTINCT group_id) FROM news_items WHERE group_id IS NOT NULL"
        ).fetchone()[0]
        before_grouped_items = db.conn.execute(
            "SELECT COUNT(*) FROM news_items WHERE group_id IS NOT NULL"
        ).fetchone()[0]
        log.info(f"Before: {before_groups} groups, {before_grouped_items} grouped items")

        if not args.skip_junk:
            n = drop_existing_junk(db, dry_run=args.dry_run)
            log.info(f"Junk pass: {'would ack' if args.dry_run else 'ack-ed'} {n} items")

        if args.dry_run:
            log.info("Dry run — skipping grouper + semantic passes")
            return 0

        log.info("Running tuned grouper across all items...")
        # Backfill = full rebuild over the entire history (not the incremental
        # windowed path the live pipeline uses).
        group_count = run_grouper(db, rebuild=True, window_days=None)
        after_grouped_items = db.conn.execute(
            "SELECT COUNT(*) FROM news_items WHERE group_id IS NOT NULL"
        ).fetchone()[0]
        log.info(
            f"Fuzzy grouper: {group_count} groups, {after_grouped_items} grouped items "
            f"(Δ {after_grouped_items - before_grouped_items:+d})"
        )

        if not args.skip_semantic:
            api_key = os.environ.get("ANTHROPIC_API_KEY") or cfg.get("anthropic_api_key")
            if not api_key:
                log.error("No ANTHROPIC_API_KEY — skipping semantic pass")
                return 1
            client = anthropic.Anthropic(api_key=api_key)
            model = args.model or cfg["model"]
            log.info(f"Deep semantic dedup (model={model}, max_candidates={args.max_candidates})...")
            additional = deep_semantic_dedup(
                db,
                client,
                model,
                since_days=None,  # full history
                max_candidates=args.max_candidates,
            )
            log.info(f"Semantic dedup added {additional} new groupings")

        final_groups = db.conn.execute(
            "SELECT COUNT(DISTINCT group_id) FROM news_items WHERE group_id IS NOT NULL"
        ).fetchone()[0]
        final_grouped = db.conn.execute(
            "SELECT COUNT(*) FROM news_items WHERE group_id IS NOT NULL"
        ).fetchone()[0]
        log.info(
            f"Final: {final_groups} groups, {final_grouped} grouped items "
            f"(Δ {final_grouped - before_grouped_items:+d})"
        )
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
