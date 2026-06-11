#!/usr/bin/env python3
"""Nightly episode orchestrator — runs the whole video pipeline.

Chains the three stages for today's episode and prunes old artifacts:

    1. generate_video_script.py   story selection + script   (Claude)
    2. generate_voiceover.py      narration + word marks     (ElevenLabs)
    3. generate_video.py          render + feed update       (Remotion Lambda)

Designed for cron (all output to stdout; the cron line redirects to
data/episode.log). Skips cleanly when today's episode already exists or
when no scriptworthy stories are found.

Cron slot: 19:00 UTC, an hour after the daily open-sources digest.
Requires ELEVENLABS_API_KEY in the environment (sourced from .env).
"""

import argparse
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent


def _log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}Z] {msg}", flush=True)


def _stage(name: str, cmd: "list[str]") -> bool:
    _log(f"--- stage: {name} ---")
    started = time.monotonic()
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    elapsed = time.monotonic() - started
    if result.returncode != 0:
        _log(f"FAILED: {name} (exit {result.returncode}, {elapsed:.0f}s)")
        return False
    _log(f"ok: {name} ({elapsed:.0f}s)")
    return True


def main():
    parser = argparse.ArgumentParser(description="Run the full nightly episode pipeline")
    parser.add_argument("--force", action="store_true",
                        help="Regenerate even if today's episode already exists")
    args = parser.parse_args()

    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    py = sys.executable
    out_mp4 = PROJECT_ROOT / "data" / "videos" / f"{date}.mp4"
    script_json = PROJECT_ROOT / "data" / "video_scripts" / f"{date}.json"

    _log(f"=== The Daily Prompt — episode pipeline for {date} ===")

    if out_mp4.exists() and not args.force:
        _log(f"episode already rendered ({out_mp4.name}) — nothing to do (use --force to redo)")
        return

    if not _stage("script", [py, "generate_video_script.py"]):
        sys.exit(1)
    if not script_json.exists():
        _log("no scriptworthy stories today — no episode (this is fine)")
        return

    if not _stage("voiceover", [py, "generate_voiceover.py"]):
        sys.exit(1)
    if not _stage("render + feed", [py, "generate_video.py"]):
        sys.exit(1)

    # Housekeeping: keep 30 days of episodes, 7 days of intermediate audio
    from ainews.video.maintenance import prune_old_episodes

    removed = prune_old_episodes(
        PROJECT_ROOT / "data" / "videos",
        PROJECT_ROOT / "data" / "video_audio",
        PROJECT_ROOT / "renderer" / "public" / "audio",
    )
    if removed:
        _log(f"pruned {len(removed)} old artifacts")
        # Feed may reference a pruned episode — regenerate
        from ainews.video.feed import write_episode_feed

        write_episode_feed(
            PROJECT_ROOT / "data" / "videos",
            PROJECT_ROOT / "data" / "video_scripts",
        )

    size_mb = out_mp4.stat().st_size / 1e6 if out_mp4.exists() else 0
    _log(f"=== episode {date} complete ({size_mb:.0f} MB) — live in the feed ===")


if __name__ == "__main__":
    main()
