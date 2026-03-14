#!/usr/bin/env python3
"""AI News Aggregator — fetch, process, and store pipeline."""

import argparse
import sys
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime
from pathlib import Path

import anthropic

from ainews.config import load_config
from ainews.fetchers.content_fetcher import fetch_content_for_items
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

    # Configure logging — file handler only when running under cron (no tty),
    # stdout only when running interactively, to avoid double-logging.
    handlers = [handler]
    if sys.stdout.isatty():
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=logging.INFO,
        format='%(message)s',
        handlers=handlers,
    )

    return logging.getLogger(__name__)


def write_last_run_timestamp(timestamp_path: Path):
    """Write timestamp of pipeline completion for dashboard display."""
    timestamp_path.parent.mkdir(parents=True, exist_ok=True)
    with open(timestamp_path, 'w') as f:
        f.write(datetime.now().isoformat())


def get_due_feeds(feeds: list[dict], cfg: dict, db: Database) -> list[dict]:
    """Return only feeds whose category interval has elapsed since their last scan."""
    now = datetime.now()
    trusted_interval = cfg.get("trusted_interval", 15)
    open_interval = cfg.get("open_interval", 1440)
    due = []
    for feed in feeds:
        if not feed.get("enabled", True):
            continue
        category = feed.get("category", "trusted")
        interval_minutes = trusted_interval if category == "trusted" else open_interval
        last_scanned_str = db.get_feed_last_scanned(feed["name"])
        if last_scanned_str:
            last_scanned = datetime.fromisoformat(last_scanned_str)
            elapsed_minutes = (now - last_scanned).total_seconds() / 60
            if elapsed_minutes < interval_minutes:
                continue
        due.append(feed)
    return due


def get_due_queries(queries: list[dict], cfg: dict, db: Database) -> list[dict]:
    """Return only search queries whose category interval has elapsed."""
    now = datetime.now()
    trusted_interval = cfg.get("trusted_interval", 15)
    open_interval = cfg.get("open_interval", 1440)
    due = []
    for q in queries:
        category = q.get("category", "open")
        interval_minutes = trusted_interval if category == "trusted" else open_interval
        last_scanned_str = db.get_feed_last_scanned(f"search:{q['query']}")
        if last_scanned_str:
            last_scanned = datetime.fromisoformat(last_scanned_str)
            elapsed_minutes = (now - last_scanned).total_seconds() / 60
            if elapsed_minutes < interval_minutes:
                continue
        due.append(q)
    return due


def main():
    parser = argparse.ArgumentParser(description="AI News Aggregator — fetch pipeline")
    parser.add_argument(
        "--category", choices=["trusted", "open"],
        help="Only process sources of this category (default: all)",
    )
    args = parser.parse_args()
    category_filter = args.category

    # Load config first to get data directory path
    cfg = load_config()
    data_dir = Path(cfg.get("db_path", "data/ainews.db")).parent

    # Set up logging with rotation
    logger = setup_logging(data_dir / "pipeline.log")

    start_time = datetime.now()
    label = f" ({category_filter} only)" if category_filter else ""
    logger.info("\n" + "=" * 60)
    logger.info(f"AI News Aggregator — Fetch Pipeline{label}")
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

    # Filter feeds and queries by category if specified
    feeds = cfg["feeds"]
    all_queries = cfg["search_queries"]
    if category_filter:
        feeds = [f for f in feeds if f.get("category", "trusted") == category_filter]
        all_queries = [q for q in all_queries if q.get("category", "open") == category_filter]

    # 3. Fetch RSS feeds (only those due for scanning)
    due_feeds = get_due_feeds(feeds, cfg, db)
    enabled_count = sum(1 for f in feeds if f.get("enabled", True))
    logger.info(f"\n[3/8] Fetching RSS feeds ({len(due_feeds)}/{enabled_count} feeds due)...")
    rss_items = fetch_all_feeds(
        due_feeds,
        timeout=cfg["feed_timeout"],
        max_items=cfg["max_items_per_feed"],
    )
    logger.info(f"  Total RSS items: {len(rss_items)}")

    # Record scan timestamps for feeds that were fetched
    scan_time = datetime.now().isoformat()
    for feed in due_feeds:
        db.update_feed_last_scanned(feed["name"], scan_time)

    # 4. Search DuckDuckGo (only queries due for scanning)
    due_queries = get_due_queries(all_queries, cfg, db)
    logger.info(f"\n[4/8] Searching DuckDuckGo ({len(due_queries)}/{len(all_queries)} queries due)...")
    search_items = search_all_queries(
        due_queries,
        max_results=cfg["max_search_results"],
    )
    logger.info(f"  Total search items: {len(search_items)}")

    # Record scan timestamps for queries that were searched
    query_scan_time = datetime.now().isoformat()
    for q in due_queries:
        db.update_feed_last_scanned(f"search:{q['query']}", query_scan_time)

    # 4b. Fetch newsletter emails (only on open/daily schedule)
    email_items = []
    nl_cfg = cfg.get("newsletters", {})
    if nl_cfg.get("enabled") and (not category_filter or category_filter == "open"):
        logger.info("\n[4b] Checking newsletter emails...")
        from ainews.fetchers.email_fetcher import fetch_all_newsletters
        email_items = fetch_all_newsletters(cfg, db)
        logger.info(f"  Total email items: {len(email_items)}")

    # 5. Combine and deduplicate (against batch + existing DB items)
    combined = rss_items + search_items + email_items
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

    # 5c. Fetch full article content (after dedup, before scoring)
    content_count = 0
    if cfg.get("content_fetching", True) and new_items:
        logger.info(f"\n[5c] Fetching article content for {len(new_items)} items...")
        content_count = fetch_content_for_items(
            new_items,
            max_content_length=cfg.get("content_max_chars", 10000),
            max_concurrent=10,
            timeout=15,
        )
        logger.info(f"  Got content for {content_count}/{len(new_items)} items")

    # 6. Score with Claude
    logger.info(f"\n[6/8] Scoring {len(new_items)} items with Claude ({cfg['model']})...")
    client = anthropic.Anthropic(api_key=api_key)
    processed = score_items(
        client, cfg["model"], new_items,
        batch_size=cfg.get("scoring_batch_size", 10),
        scoring_prompt=cfg.get("scoring_prompt"),
        categories=cfg.get("categories"),
        content_max=cfg.get("content_score_chars", 3000),
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
    """Generate RSS feeds (combined + trusted/digest splits)."""
    output_path = cfg.get("rss_output_path", "data/high_priority.xml")
    min_score = cfg.get("rss_min_score", 8)

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Build list of trusted source names from config
    trusted_sources = [
        f["name"]
        for f in cfg.get("feeds", [])
        if f.get("category") == "trusted" and f.get("enabled", True)
    ]

    rss_count = save_rss_feed(
        db, str(output_file), min_score=min_score,
        trusted_sources=trusted_sources,
    )
    logger.info(f"  RSS feeds generated: {output_path} ({rss_count} items)")
    logger.info(f"    + {output_file.stem}_trusted{output_file.suffix}")
    logger.info(f"    + {output_file.stem}_digest{output_file.suffix}")

    return rss_count


if __name__ == "__main__":
    main()
