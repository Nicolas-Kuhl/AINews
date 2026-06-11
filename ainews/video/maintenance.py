"""Disk housekeeping for the video pipeline.

Episodes are ~45 MB each on a 20 GB instance disk — without pruning, the
nightly pipeline would fill the disk in under a year. Keeps a rolling
window of rendered episodes and their intermediate audio.
"""

from __future__ import annotations

import logging
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_DATED = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def prune_old_episodes(
    videos_dir: Path,
    audio_dir: Path,
    staged_audio_dir: Path,
    *,
    keep_video_days: int = 30,
    keep_audio_days: int = 7,
    now: "datetime | None" = None,
) -> "list[str]":
    """Delete episode artifacts older than the retention windows.

    Returns the names of removed items. Only date-prefixed artifacts are
    touched; feed.xml and anything unrecognized is left alone.
    """
    now = now or datetime.now(timezone.utc)
    removed: "list[str]" = []

    def _cutoff(days: int) -> str:
        return (now - timedelta(days=days)).strftime("%Y-%m-%d")

    video_cutoff = _cutoff(keep_video_days)
    if videos_dir.exists():
        for f in videos_dir.iterdir():
            m = _DATED.match(f.name)
            if f.is_file() and m and m.group(1) < video_cutoff:
                f.unlink()
                removed.append(f.name)

    audio_cutoff = _cutoff(keep_audio_days)
    for base in (audio_dir, staged_audio_dir):
        if not base.exists():
            continue
        for d in base.iterdir():
            m = _DATED.match(d.name)
            if d.is_dir() and m and m.group(1) < audio_cutoff:
                shutil.rmtree(d)
                removed.append(f"{d.name}/")

    if removed:
        logger.info("Pruned %d old artifacts: %s", len(removed), ", ".join(sorted(removed)))
    return removed
