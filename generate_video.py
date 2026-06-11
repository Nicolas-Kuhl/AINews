#!/usr/bin/env python3
"""Render the daily episode video.

Stage 3 of the video pipeline: combines the script JSON (Stage 1) and the
voiceover audio (Stage 2) into an MP4 via the Remotion project in renderer/.

Usage:
    python generate_video.py                     # today's episode
    python generate_video.py --date 2026-06-10
    python generate_video.py --still 450         # render frame 450 as PNG (preview)

Requires: node >= 18 and `npm install` run once inside renderer/.
"""

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from ainews.config import load_config
from ainews.video.render import build_render_manifest, write_render_manifest

PROJECT_ROOT = Path(__file__).parent
RENDERER_DIR = PROJECT_ROOT / "renderer"


def main():
    parser = argparse.ArgumentParser(description="Render the daily episode MP4")
    parser.add_argument("--date", type=str, help="Episode date YYYY-MM-DD (default: today UTC)")
    parser.add_argument("--output", type=str, help="Output MP4 path")
    parser.add_argument("--still", type=int, metavar="FRAME",
                        help="Render a single frame as PNG instead of the full video")
    parser.add_argument("--preview", action="store_true",
                        help="Fast test render: half resolution, 2 render workers")
    parser.add_argument("--concurrency", type=int,
                        help="Override Chromium render workers (default: 1, preview: 2)")
    args = parser.parse_args()

    date = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    script_path = PROJECT_ROOT / "data" / "video_scripts" / f"{date}.json"
    audio_dir = PROJECT_ROOT / "data" / "video_audio" / date
    audio_manifest_path = audio_dir / "manifest.json"

    for p, hint in ((script_path, "generate_video_script.py"),
                    (audio_manifest_path, "generate_voiceover.py")):
        if not p.exists():
            print(f"ERROR: {p} not found — run {hint} first.")
            sys.exit(1)

    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)
    with open(audio_manifest_path, encoding="utf-8") as f:
        audio_manifest = json.load(f)

    cfg = load_config()
    show_name = cfg.get("video_script", {}).get("show_name", "The Daily Prompt")

    # Stage audio under renderer/public so Remotion's staticFile() can see it
    public_audio = RENDERER_DIR / "public" / "audio" / date
    public_audio.mkdir(parents=True, exist_ok=True)
    for entry in audio_manifest["sections"]:
        shutil.copy2(audio_dir / entry["audio"], public_audio / entry["audio"])

    manifest = build_render_manifest(
        script, audio_manifest, audio_dir,
        audio_rel_prefix=f"audio/{date}", show_name=show_name, date=date,
    )
    props_path = write_render_manifest(manifest, RENDERER_DIR / "public" / f"props-{date}.json")

    total = sum(s["durationSeconds"] for s in manifest["sections"])
    print(f"Episode {date}: {len(manifest['sections'])} sections, "
          f"{int(total // 60)}:{int(total % 60):02d} runtime")

    extra_flags = []
    if args.preview:
        # Half resolution + two workers: ~3-4x faster, plenty for layout and
        # timing checks. Preview output is suffixed so it never enters the
        # podcast feed (the feed only picks up <date>.mp4).
        extra_flags += ["--scale=0.5", "--concurrency=2"]
    if args.concurrency:
        extra_flags = [f for f in extra_flags if not f.startswith("--concurrency")]
        extra_flags.append(f"--concurrency={args.concurrency}")

    if args.still is not None:
        out = PROJECT_ROOT / "data" / "videos" / f"{date}-frame{args.still}.png"
        cmd = ["npx", "remotion", "still", "src/index.ts", "Episode", str(out),
               f"--frame={args.still}", f"--props={props_path}", *extra_flags]
    elif args.preview:
        out = PROJECT_ROOT / "data" / "videos" / f"{date}-preview.mp4"
        cmd = ["npx", "remotion", "render", "src/index.ts", "Episode", str(out),
               f"--props={props_path}", *extra_flags]
    else:
        out = Path(args.output) if args.output else PROJECT_ROOT / "data" / "videos" / f"{date}.mp4"
        cmd = ["npx", "remotion", "render", "src/index.ts", "Episode", str(out),
               f"--props={props_path}", *extra_flags]

    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"Rendering -> {out}")
    result = subprocess.run(cmd, cwd=RENDERER_DIR)
    if result.returncode != 0:
        print("ERROR: Remotion render failed")
        sys.exit(result.returncode)

    size_mb = out.stat().st_size / 1e6
    print(f"\n✓ Rendered: {out} ({size_mb:.1f} MB)")

    # Refresh the episode podcast feed so the new video is subscribable.
    if args.still is None:
        from ainews.video.feed import write_episode_feed

        feed_path, count = write_episode_feed(
            PROJECT_ROOT / "data" / "videos",
            PROJECT_ROOT / "data" / "video_scripts",
            show_name=show_name,
        )
        print(f"✓ Feed updated: {feed_path} ({count} episodes)")


if __name__ == "__main__":
    main()
