#!/usr/bin/env python3
"""One-off: re-cluster the entire history with the embedding clusterer.

Clears every group_id and rebuilds story clusters from semantic embeddings
(centroid + time-window). Embeds any item without a stored vector first —
on first run that is the whole database (~10-15 min, a few cents of Titan).

Run after deploying the embedding clusterer:
    venv/bin/python scripts/recluster_backfill.py [--threshold 0.80] [--dry-run-report]
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ainews.config import load_config  # noqa: E402
from ainews.processing.clusterer import cluster_recent_items  # noqa: E402
from ainews.processing.embeddings import TitanEmbedder  # noqa: E402
from ainews.storage.database import Database  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Re-cluster all items with embeddings")
    parser.add_argument("--threshold", type=float, help="Cosine threshold override")
    parser.add_argument("--max-span-days", type=int, help="Cluster time-span cap override")
    args = parser.parse_args()

    cfg = load_config()
    ecfg = cfg.get("embeddings", {})
    db = Database(cfg["db_path"])
    embedder = TitanEmbedder(
        model_id=ecfg.get("model_id", "amazon.titan-embed-text-v2:0"),
        region=ecfg.get("region", "us-east-1"),
        dimensions=ecfg.get("dimensions", 512),
    )

    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    started = time.monotonic()
    touched = cluster_recent_items(
        db, embedder,
        threshold=args.threshold or ecfg.get("threshold", 0.80),
        window_days=None,  # full history
        max_span_days=args.max_span_days or ecfg.get("max_span_days", 4),
        rebuild=True,
    )
    elapsed = time.monotonic() - started

    # Post-rebuild sanity report
    total = db.conn.execute("SELECT COUNT(*) FROM news_items").fetchone()[0]
    grouped = db.conn.execute(
        "SELECT COUNT(*) FROM news_items WHERE group_id IS NOT NULL").fetchone()[0]
    n_groups = db.conn.execute(
        "SELECT COUNT(DISTINCT group_id) FROM news_items WHERE group_id IS NOT NULL"
    ).fetchone()[0]
    biggest = db.conn.execute(
        "SELECT group_id, COUNT(*) c FROM news_items WHERE group_id IS NOT NULL "
        "GROUP BY group_id ORDER BY c DESC LIMIT 5"
    ).fetchall()
    db.close()

    print(f"\nRebuilt in {elapsed:.0f}s: {n_groups} clusters touched={touched}")
    print(f"Items: {total} total, {grouped} grouped, {total - grouped} singletons")
    print("Largest clusters:")
    for r in biggest:
        print(f"  group {r[0]}: {r[1]} members")


if __name__ == "__main__":
    main()
