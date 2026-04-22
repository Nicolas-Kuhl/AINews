#!/usr/bin/env python3
"""Re-derive the `sources` table type/short/mark/hue for every distinct
source in ``news_items``.

Overwrites existing rows — use this after changing the heuristic or the
config.yaml feeds list. Operator edits (if any) are wiped.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ainews.config import load_config  # noqa: E402
from ainews.dashboard.payload import ensure_source_metas  # noqa: E402
from ainews.storage.database import Database  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a per-type histogram after refresh",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("refresh_source_metas")

    cfg = load_config()
    db = Database(cfg["db_path"])
    try:
        metas = ensure_source_metas(
            db, refresh_all=True, config_feeds=cfg.get("feeds")
        )
        log.info("Refreshed %d source rows", len(metas))
        if args.summary:
            counts: dict[str, int] = {}
            for m in metas.values():
                counts[m["type"]] = counts.get(m["type"], 0) + 1
            for t, n in sorted(counts.items()):
                log.info("  %s: %d", t, n)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
