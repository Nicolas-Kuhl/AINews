#!/usr/bin/env python3
"""AI News Aggregator — fetch, process, and store pipeline."""

import sys

import anthropic

from ainews.config import load_config
from ainews.fetchers.rss_fetcher import fetch_all_feeds
from ainews.fetchers.web_searcher import search_all_queries
from ainews.processing.deduplicator import deduplicate
from ainews.processing.grouper import run_grouper
from ainews.processing.scorer import score_items
from ainews.storage.database import Database


def main():
    print("=" * 60)
    print("AI News Aggregator — Fetch Pipeline")
    print("=" * 60)

    # 1. Load config
    print("\n[1/7] Loading configuration...")
    cfg = load_config()
    api_key = cfg.get("anthropic_api_key", "")
    if not api_key:
        print("ERROR: No Anthropic API key found.")
        print("Set ANTHROPIC_API_KEY env var or add to config.yaml")
        sys.exit(1)

    # 2. Initialize DB
    print("[2/7] Initializing database...")
    db = Database(cfg["db_path"])

    # 3. Fetch RSS feeds
    print(f"\n[3/7] Fetching RSS feeds ({len(cfg['feeds'])} feeds)...")
    rss_items = fetch_all_feeds(
        cfg["feeds"],
        timeout=cfg["feed_timeout"],
        max_items=cfg["max_items_per_feed"],
    )
    print(f"  Total RSS items: {len(rss_items)}")

    # 4. Search DuckDuckGo
    print(f"\n[4/7] Searching DuckDuckGo ({len(cfg['search_queries'])} queries)...")
    search_items = search_all_queries(
        cfg["search_queries"],
        max_results=cfg["max_search_results"],
    )
    print(f"  Total search items: {len(search_items)}")

    # 5. Combine and deduplicate
    combined = rss_items + search_items
    print(f"\n[5/7] Deduplicating {len(combined)} items...")
    unique = deduplicate(combined, threshold=cfg["dedup_threshold"])

    # Filter out items already in the database
    new_items = [item for item in unique if not db.url_exists(item.url)]
    print(f"  After dedup: {len(unique)} unique items")
    print(f"  New (not in DB): {len(new_items)} items")

    if not new_items:
        print("\nNo new items to process. Done!")
        db.close()
        return

    # 6. Score with Claude
    print(f"\n[6/7] Scoring {len(new_items)} items with Claude ({cfg['model']})...")
    client = anthropic.Anthropic(api_key=api_key)
    processed = score_items(
        client, cfg["model"], new_items,
        batch_size=cfg.get("scoring_batch_size", 10),
        scoring_prompt=cfg.get("scoring_prompt"),
    )

    # Store results
    stored = 0
    for item in processed:
        row_id = db.insert(item)
        if row_id:
            stored += 1

    # 7. Run smart grouper
    print("\n[7/7] Running smart grouper...")
    group_count = run_grouper(db)
    print(f"  Created {group_count} groups")

    db.close()

    # Summary
    print("\n" + "=" * 60)
    print("Pipeline Complete!")
    print(f"  Fetched: {len(combined)} total items")
    print(f"  Unique:  {len(unique)} after dedup")
    print(f"  New:     {len(new_items)} not in DB")
    print(f"  Stored:  {stored} items")
    print(f"  Groups:  {group_count}")
    print("=" * 60)
    print("\nRun 'streamlit run dashboard.py' to view results.")


if __name__ == "__main__":
    main()
