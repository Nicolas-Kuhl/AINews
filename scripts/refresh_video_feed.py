#!/usr/bin/env python3
"""Regenerate the episode podcast feed (data/videos/feed.xml) from disk.

Normally the feed refreshes automatically after each render; this script
covers manual cases (moved/removed episode files, feed format changes).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ainews.config import load_config  # noqa: E402
from ainews.video.feed import write_episode_feed  # noqa: E402


def main():
    root = Path(__file__).parent.parent
    cfg = load_config()
    show_name = cfg.get("video_script", {}).get("show_name", "The Daily Prompt")
    path, count = write_episode_feed(
        root / "data" / "videos",
        root / "data" / "video_scripts",
        show_name=show_name,
    )
    print(f"feed: {path} ({count} episodes)")


if __name__ == "__main__":
    main()
