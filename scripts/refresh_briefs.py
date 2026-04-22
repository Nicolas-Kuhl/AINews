#!/usr/bin/env python3
"""Refresh Morning + Day Briefs for the triage console.

Usage:
    python scripts/refresh_briefs.py [--force] [--days N] [--model MODEL]

Defaults: writes a Morning Brief for today and Day Briefs for the last 5 days
(only for days missing a brief unless --force is set).
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
from ainews.processing.brief import DEFAULT_BRIEF_MODEL, refresh_briefs  # noqa: E402
from ainews.storage.database import Database  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Regenerate even if a brief exists")
    parser.add_argument("--days", type=int, default=5, help="Lookback window for Day Briefs")
    parser.add_argument("--model", default=DEFAULT_BRIEF_MODEL, help="Claude model id")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("refresh_briefs")

    cfg = load_config()
    api_key = os.environ.get("ANTHROPIC_API_KEY") or cfg.get("anthropic_api_key")
    if not api_key:
        log.error("No ANTHROPIC_API_KEY found in env or config.yaml")
        return 1

    client = anthropic.Anthropic(api_key=api_key)
    db = Database(cfg["db_path"])
    try:
        summary = refresh_briefs(
            db,
            client,
            lookback_days=args.days,
            model=args.model,
            force=args.force,
            logger=log,
        )
    finally:
        db.close()

    log.info("Done: morning=%s days=%s", summary.get("morning"), summary.get("days"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
