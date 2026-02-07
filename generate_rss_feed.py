#!/usr/bin/env python3
"""Generate RSS feed for high-priority AI news items.

This script generates an RSS feed XML file containing news items
with a score of 8 or above. The feed can be served via a web server
or uploaded to a static hosting service for RSS reader subscriptions.

Usage:
    python generate_rss_feed.py [--min-score 8] [--output data/high_priority.xml]
"""

import argparse
from pathlib import Path

from ainews.config import load_config
from ainews.rss_generator import save_rss_feed
from ainews.storage.database import Database


def main():
    parser = argparse.ArgumentParser(description="Generate RSS feed for high-priority AI news")
    parser.add_argument(
        "--min-score",
        type=int,
        default=8,
        help="Minimum score for items to include (default: 8)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/high_priority.xml",
        help="Output path for RSS XML file (default: data/high_priority.xml)"
    )
    parser.add_argument(
        "--include-acknowledged",
        action="store_true",
        help="Include acknowledged items in the feed"
    )

    args = parser.parse_args()

    # Load config and database
    project_root = Path(__file__).parent
    cfg = load_config()
    db = Database(project_root / "data" / "ainews.db")

    # Generate RSS feed
    print(f"Generating RSS feed with minimum score {args.min_score}...")
    item_count = save_rss_feed(db, args.output, min_score=args.min_score)

    print(f"✓ RSS feed generated: {args.output}")
    print(f"  Items included: {item_count}")
    print(f"  Minimum score: {args.min_score}")
    print()
    print("To serve this feed:")
    print(f"  1. Start a simple HTTP server: python -m http.server 8080")
    print(f"  2. Subscribe in your RSS reader: http://localhost:8080/{args.output}")
    print()
    print("Or upload the XML file to your web hosting and subscribe to that URL.")


if __name__ == "__main__":
    main()
