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
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from ainews.runlock import RunLockBusy, run_lock

PROJECT_ROOT = Path(__file__).parent


def _log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}Z] {msg}", flush=True)


def _alert(subject: str, message: str) -> None:
    """Best-effort failure notification via SNS (AINEWS_ALERT_TOPIC_ARN).

    Alerting must never make a bad night worse: all errors here are
    swallowed after logging.
    """
    topic_arn = os.environ.get("AINEWS_ALERT_TOPIC_ARN", "").strip()
    if not topic_arn:
        _log("(no AINEWS_ALERT_TOPIC_ARN set — skipping failure alert)")
        return
    try:
        import boto3

        region = topic_arn.split(":")[3]
        boto3.client("sns", region_name=region).publish(
            TopicArn=topic_arn,
            Subject=subject[:99],  # SNS subject limit
            Message=message,
        )
        _log("failure alert sent")
    except Exception as exc:  # noqa: BLE001
        _log(f"WARNING: could not send alert: {exc}")


def _retry_command(date: str) -> str:
    return (
        "cd /opt/ainews && set -a && . ./.env && set +a && "
        f"venv/bin/python generate_episode.py --date {date}"
    )


def _stage(name: str, cmd: "list[str]", date: str) -> bool:
    _log(f"--- stage: {name} ---")
    started = time.monotonic()
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    elapsed = time.monotonic() - started
    if result.returncode != 0:
        _log(f"FAILED: {name} (exit {result.returncode}, {elapsed:.0f}s)")
        _alert(
            f"The Daily Prompt: nightly episode FAILED at stage '{name}'",
            f"Stage '{name}' exited {result.returncode} after {elapsed:.0f}s.\n"
            f"Command: {' '.join(cmd)}\n"
            f"Check /opt/ainews/data/episode.log for details.\n"
            f"Retry manually: {_retry_command(date)}",
        )
        return False
    _log(f"ok: {name} ({elapsed:.0f}s)")
    return True


def main():
    parser = argparse.ArgumentParser(description="Run the full nightly episode pipeline")
    parser.add_argument("--force", action="store_true",
                        help="Regenerate even if today's episode already exists")
    parser.add_argument("--date", type=str, metavar="YYYY-MM-DD",
                        help="Edition date (default: today UTC). Use the date from a "
                             "failure alert to finish that night's episode.")
    args = parser.parse_args()

    # Fixed once and passed to every stage: each stage computing "today" on
    # its own meant a retry after midnight UTC built tomorrow's episode (and
    # tomorrow's cron then skipped it as "already rendered").
    date = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        with run_lock(PROJECT_ROOT / "data" / ".episode.lock"):
            _run_episode(date, force=args.force)
    except RunLockBusy:
        _log("another episode run is still in progress — skipping")


def _run_episode(date: str, *, force: bool) -> None:
    py = sys.executable
    out_mp4 = PROJECT_ROOT / "data" / "videos" / f"{date}.mp4"
    script_json = PROJECT_ROOT / "data" / "video_scripts" / f"{date}.json"

    _log(f"=== The Daily Prompt — episode pipeline for {date} ===")

    # Skip only when the episode is fully complete (script AND video). A
    # missing script means a regeneration was requested (delete the script
    # to re-run with fresh stories); a missing mp4 means a prior run failed
    # mid-pipeline — both should run.
    if out_mp4.exists() and script_json.exists() and not force:
        _log(f"episode already rendered ({out_mp4.name}) — nothing to do (use --force to redo)")
        return

    # A retry resumes where the last run failed: a finished stage's output is
    # reused rather than paid for again (Claude for the script, ElevenLabs
    # for the voiceover). --force regenerates everything.
    if script_json.exists() and not force:
        _log(f"reusing existing script {script_json.name}")
    else:
        if not _stage("script", [py, "generate_video_script.py", "--edition-date", date], date):
            sys.exit(1)
        if not script_json.exists():
            _log("no scriptworthy stories today — no episode (this is fine)")
            return

    manifest = PROJECT_ROOT / "data" / "video_audio" / date / "manifest.json"
    voiceover_done = (
        manifest.exists() and manifest.stat().st_mtime >= script_json.stat().st_mtime
    )
    if voiceover_done and not force:
        _log(f"reusing existing voiceover for {date}")
    elif not _stage("voiceover", [py, "generate_voiceover.py", "--script", str(script_json)], date):
        sys.exit(1)
    if not _stage("render + feed", [py, "generate_video.py", "--date", date], date):
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
