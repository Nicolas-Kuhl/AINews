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


def _instance_role_env() -> dict:
    """Fetch the EC2 instance role's temporary credentials as env vars.

    The Remotion Lambda SDK requires explicit AWS_* env vars and won't use
    the instance-role chain itself. Returns {} off-EC2 (local dev relies on
    the ambient environment instead).
    """
    import urllib.request

    imds = "http://169.254.169.254/latest"
    try:
        token = urllib.request.urlopen(
            urllib.request.Request(
                f"{imds}/api/token", method="PUT",
                headers={"X-aws-ec2-metadata-token-ttl-seconds": "900"},
            ), timeout=2,
        ).read().decode()
        headers = {"X-aws-ec2-metadata-token": token}
        role = urllib.request.urlopen(
            urllib.request.Request(
                f"{imds}/meta-data/iam/security-credentials/", headers=headers,
            ), timeout=2,
        ).read().decode().strip()
        creds = json.loads(urllib.request.urlopen(
            urllib.request.Request(
                f"{imds}/meta-data/iam/security-credentials/{role}", headers=headers,
            ), timeout=2,
        ).read())
        return {
            "AWS_ACCESS_KEY_ID": creds["AccessKeyId"],
            "AWS_SECRET_ACCESS_KEY": creds["SecretAccessKey"],
            "AWS_SESSION_TOKEN": creds["Token"],
        }
    except Exception:
        return {}


def _stage_audio_on_s3(manifest: dict, audio_dir: Path, date: str, video_cfg: dict) -> dict:
    """Upload episode audio to S3 and swap props audio paths for presigned URLs."""
    import boto3

    bucket = video_cfg.get("assets_bucket", "ainews-render-assets")
    region = video_cfg.get("lambda_region", "us-east-1")
    s3 = boto3.client("s3", region_name=region)

    for section in manifest["sections"]:
        if section["kind"] == "intro":
            continue  # site-bundled static asset, not per-episode audio
        filename = Path(section["audio"]).name
        key = f"audio/{date}/{filename}"
        s3.upload_file(str(audio_dir / filename), bucket, key)
        section["audio"] = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=4 * 3600,
        )
    print(f"Audio staged on s3://{bucket}/audio/{date}/ (presigned, 4h)")
    return manifest


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
    parser.add_argument("--local", action="store_true",
                        help="Render on this machine instead of Remotion Lambda")
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
    video_cfg = cfg.get("video", {})
    # Stills and previews are quick local Chromium jobs; full renders go to
    # Remotion Lambda unless --local or render_engine says otherwise.
    use_lambda = (
        video_cfg.get("render_engine", "lambda") == "lambda"
        and not args.local
        and not args.preview
        and args.still is None
    )

    # Branded musical intro, if the sting asset has been chosen and committed
    sting = RENDERER_DIR / "public" / "branding" / "intro-sting.mp3"
    intro_audio = "branding/intro-sting.mp3" if sting.exists() else None

    manifest = build_render_manifest(
        script, audio_manifest, audio_dir,
        audio_rel_prefix=f"audio/{date}", show_name=show_name, date=date,
        intro_audio=intro_audio,
    )

    if use_lambda:
        # Lambda renderers can't reach this disk — audio goes to S3 and the
        # props point at presigned URLs (valid well past any render).
        manifest = _stage_audio_on_s3(manifest, audio_dir, date, video_cfg)
    else:
        # Stage audio under renderer/public so Remotion's staticFile() sees it
        public_audio = RENDERER_DIR / "public" / "audio" / date
        public_audio.mkdir(parents=True, exist_ok=True)
        for entry in audio_manifest["sections"]:
            shutil.copy2(audio_dir / entry["audio"], public_audio / entry["audio"])

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
    elif use_lambda:
        # Resolve to absolute: the node driver runs with cwd=renderer/.
        out = (Path(args.output).resolve() if args.output
               else PROJECT_ROOT / "data" / "videos" / f"{date}.mp4")
        cmd = ["node", "render-lambda.mjs", str(props_path), str(out),
               video_cfg.get("lambda_region", "us-east-1"),
               video_cfg.get("lambda_site", "ainews")]
    else:
        out = Path(args.output) if args.output else PROJECT_ROOT / "data" / "videos" / f"{date}.mp4"
        cmd = ["npx", "remotion", "render", "src/index.ts", "Episode", str(out),
               f"--props={props_path}", *extra_flags]

    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"Rendering -> {out}")
    env = None
    if use_lambda:
        import os

        env = {
            **os.environ,
            **_instance_role_env(),
            "AWS_REGION": video_cfg.get("lambda_region", "us-east-1"),
        }
    result = subprocess.run(cmd, cwd=RENDERER_DIR, env=env)
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
