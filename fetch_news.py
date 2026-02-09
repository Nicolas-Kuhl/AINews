#!/usr/bin/env python3
"""AI News Aggregator — fetch, process, and store pipeline."""

import sys
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime
from pathlib import Path

import anthropic

from ainews.config import load_config
from ainews.fetchers.rss_fetcher import fetch_all_feeds
from ainews.fetchers.web_searcher import search_all_queries
from ainews.processing.deduplicator import deduplicate, semantic_dedup
from ainews.processing.grouper import run_grouper
from ainews.processing.scorer import score_items
from ainews.rss_generator import save_rss_feed
from ainews.storage.database import Database


def setup_logging(log_path: Path):
    """Set up rotating file handler for pipeline logs."""
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Create rotating handler: rotates at midnight, keeps 7 days
    handler = TimedRotatingFileHandler(
        filename=log_path,
        when='midnight',
        interval=1,
        backupCount=7,
        encoding='utf-8'
    )
    handler.suffix = '%Y-%m-%d'

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(message)s',
        handlers=[handler, logging.StreamHandler(sys.stdout)]
    )

    return logging.getLogger(__name__)


def write_last_run_timestamp(timestamp_path: Path):
    """Write timestamp of pipeline completion for dashboard display."""
    timestamp_path.parent.mkdir(parents=True, exist_ok=True)
    with open(timestamp_path, 'w') as f:
        f.write(datetime.now().isoformat())


def main():
    # Load config first to get data directory path
    cfg = load_config()
    data_dir = Path(cfg.get("db_path", "data/ainews.db")).parent

    # Set up logging with rotation
    logger = setup_logging(data_dir / "pipeline.log")

    start_time = datetime.now()
    logger.info("\n" + "=" * 60)
    logger.info("AI News Aggregator — Fetch Pipeline")
    logger.info(f"Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    # 1. Load config (already loaded above)
    logger.info("\n[1/8] Loading configuration...")
    api_key = cfg.get("anthropic_api_key", "")
    if not api_key:
        logger.error("ERROR: No Anthropic API key found.")
        logger.error("Set ANTHROPIC_API_KEY env var or add to config.yaml")
        sys.exit(1)

    # 2. Initialize DB
    logger.info("[2/8] Initializing database...")
    db = Database(cfg["db_path"])

    # 3. Fetch RSS feeds
    logger.info(f"\n[3/8] Fetching RSS feeds ({len(cfg['feeds'])} feeds)...")
    rss_items = fetch_all_feeds(
        cfg["feeds"],
        timeout=cfg["feed_timeout"],
        max_items=cfg["max_items_per_feed"],
    )
    logger.info(f"  Total RSS items: {len(rss_items)}")

    # 4. Search DuckDuckGo
    logger.info(f"\n[4/8] Searching DuckDuckGo ({len(cfg['search_queries'])} queries)...")
    search_items = search_all_queries(
        cfg["search_queries"],
        max_results=cfg["max_search_results"],
    )
    logger.info(f"  Total search items: {len(search_items)}")

    # 5. Combine and deduplicate (against batch + existing DB items)
    combined = rss_items + search_items
    logger.info(f"\n[5/8] Deduplicating {len(combined)} items...")
    existing_titles = db.get_all_titles()
    existing_urls = db.get_all_normalized_urls()
    logger.info(f"  Checking against {len(existing_titles)} existing DB items")
    new_items, borderline_pairs = deduplicate(
        combined,
        threshold=cfg["dedup_threshold"],
        existing_titles=existing_titles,
        existing_urls=existing_urls,
        borderline_low=cfg.get("borderline_threshold", 50),
    )
    logger.info(f"  After fuzzy dedup: {len(new_items)} new items")
    if borderline_pairs:
        logger.info(f"  Borderline pairs for semantic review: {len(borderline_pairs)}")

    # 5b. Semantic dedup — use Claude to identify same-story pairs for grouping
    semantic_pairs: list[tuple[str, str]] = []
    if new_items and borderline_pairs and cfg.get("semantic_dedup", True):
        logger.info("  Running semantic dedup with Claude...")
        client = anthropic.Anthropic(api_key=api_key)
        semantic_pairs = semantic_dedup(client, cfg["model"], borderline_pairs)
    logger.info(f"  New unique items: {len(new_items)}")

    if not new_items:
        logger.info("\nNo new items to process. Generating RSS feed...")
        # Still generate RSS feed even if no new items
        _generate_rss_feed(db, cfg, logger)
        db.close()

        # Summary for no-new-items case
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        logger.info("\n" + "=" * 60)
        logger.info("Pipeline Complete (no new items)")
        logger.info(f"  Started:     {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"  Finished:    {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"  Duration:    {duration:.1f}s")
        logger.info("=" * 60)

        # Write timestamp for dashboard
        write_last_run_timestamp(data_dir / ".last_run")
        return

    # 6. Score with Claude
    logger.info(f"\n[6/8] Scoring {len(new_items)} items with Claude ({cfg['model']})...")
    client = anthropic.Anthropic(api_key=api_key)
    processed = score_items(
        client, cfg["model"], new_items,
        batch_size=cfg.get("scoring_batch_size", 10),
        scoring_prompt=cfg.get("scoring_prompt"),
        categories=cfg.get("categories"),
    )

    # Store results
    stored = 0
    for item in processed:
        row_id = db.insert(item)
        if row_id:
            stored += 1

    # 7. Run smart grouper
    logger.info("\n[7/8] Running smart grouper...")
    group_count = run_grouper(db)
    logger.info(f"  Created {group_count} groups")

    # 7b. Group semantic matches that the fuzzy grouper may have missed
    if semantic_pairs:
        semantic_grouped = db.group_by_title_pairs(semantic_pairs)
        if semantic_grouped:
            logger.info(f"  Semantic grouping added {semantic_grouped} additional group{'s' if semantic_grouped != 1 else ''}")

    # 8. Generate RSS feed
    logger.info("\n[8/8] Generating RSS feed...")
    rss_count = _generate_rss_feed(db, cfg, logger)

    db.close()

    # Summary
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    logger.info("\n" + "=" * 60)
    logger.info("Pipeline Complete!")
    logger.info(f"  Started:     {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"  Finished:    {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"  Duration:    {duration:.1f}s")
    logger.info(f"  Fetched:     {len(combined)} total items")
    logger.info(f"  New:         {len(new_items)} after dedup")
    logger.info(f"  Stored:      {stored} items")
    logger.info(f"  Groups:      {group_count}")
    logger.info(f"  RSS feed:    {rss_count} items (score 8+)")
    logger.info("=" * 60)
    logger.info("\nRun 'streamlit run dashboard.py' to view results.")
    logger.info("RSS feed: data/high_priority.xml")

    # Write timestamp for dashboard
    write_last_run_timestamp(data_dir / ".last_run")


def _generate_rss_feed(db, cfg, logger):
    """Generate RSS feed for high-priority items."""
    # Get output path from config or use default
    output_path = cfg.get("rss_output_path", "data/high_priority.xml")
    min_score = cfg.get("rss_min_score", 8)

    # Ensure directory exists
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Generate RSS feed
    rss_count = save_rss_feed(db, str(output_file), min_score=min_score)
    logger.info(f"  RSS feed generated: {output_path} ({rss_count} items)")

    return rss_count


if __name__ == "__main__":
    main()
