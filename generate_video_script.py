#!/usr/bin/env python3
"""Generate the daily video episode script from the top stories.

Stage 1 of the video pipeline: selects the highest-scoring story groups of
the last 24 hours and writes a structured episode script (JSON for the
TTS/render stages, Markdown for human review) to data/video_scripts/.

Usage:
    python generate_video_script.py [--hours 24] [--min-score 6]
                                    [--max-stories 7] [--minutes 5]

Intended cron slot: shortly after the daily open-sources digest, e.g.
    0 19 * * * cd /opt/ainews && venv/bin/python generate_video_script.py
"""

import argparse
import logging
import sys
from pathlib import Path

import anthropic

from ainews.config import load_config
from ainews.processing.video_script import run_video_script
from ainews.storage.database import Database


def main():
    parser = argparse.ArgumentParser(description="Generate the daily video episode script")
    parser.add_argument("--hours", type=int, help="Lookback window in hours")
    parser.add_argument("--date", type=str, metavar="YYYY-MM-DD",
                        help="Generate for an exact UTC calendar day instead of the lookback window")
    parser.add_argument("--include-covered", action="store_true",
                        help="Allow stories already used by previous episodes")
    parser.add_argument("--min-score", type=int, help="Minimum story score to consider")
    parser.add_argument("--max-stories", type=int, help="Maximum stories in the episode")
    parser.add_argument("--minutes", type=float, help="Target runtime in minutes")
    parser.add_argument("--output-dir", type=str, help="Directory for script files")
    args = parser.parse_args()

    cfg = load_config()
    vs_cfg = cfg.get("video_script", {})

    api_key = cfg.get("anthropic_api_key", "")
    if not api_key:
        print("ERROR: No Anthropic API key found.")
        print("Set ANTHROPIC_API_KEY env var or add to config.yaml")
        sys.exit(1)

    logging.basicConfig(level=logging.INFO, format="%(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])
    logger = logging.getLogger("video_script")

    project_root = Path(__file__).parent
    output_dir = Path(args.output_dir or vs_cfg.get("output_dir") or
                      project_root / "data" / "video_scripts")

    db = Database(cfg["db_path"])
    client = anthropic.Anthropic(api_key=api_key)
    try:
        result = run_video_script(
            db, client,
            output_dir=output_dir,
            hours=args.hours or vs_cfg.get("hours", 24),
            catchup_hours=vs_cfg.get("catchup_hours", 72),
            catchup_min_score=vs_cfg.get("catchup_min_score", 8),
            min_score=args.min_score or vs_cfg.get("min_score", 6),
            max_stories=args.max_stories or vs_cfg.get("max_stories", 7),
            target_minutes=args.minutes or vs_cfg.get("target_minutes", 5),
            words_per_minute=vs_cfg.get("words_per_minute", 155),
            model=vs_cfg.get("model", cfg.get("model", "claude-sonnet-4-6")),
            show_name=vs_cfg.get("show_name", "The Daily Prompt"),
            on_date=args.date,
            exclude_covered=not args.include_covered,
            logger=logger,
        )
    finally:
        db.close()

    if result["status"] == "no-stories":
        print("No scriptworthy stories in the window — nothing written.")
        return

    print()
    print(f"✓ Episode script generated: {result['json_path']}")
    print(f"  Review copy:    {result['md_path']}")
    print(f"  Stories:        {result['story_count']}")
    print(f"  Narration:      {result['narration_words']} words")
    runtime = result["estimated_runtime_seconds"]
    print(f"  Est. runtime:   {runtime // 60}:{runtime % 60:02d}")


if __name__ == "__main__":
    main()
