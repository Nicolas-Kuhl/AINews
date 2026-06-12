#!/usr/bin/env python3
"""One-off: composite a HeyGen talking-head into an episode's corner.

Experimental / manual — NOT part of the nightly pipeline. For the cold open
and the first N segments of an already-generated episode, it:

  1. uploads each section's narration mp3 to S3 (presigned, for HeyGen to fetch)
  2. asks HeyGen for an avatar lip-synced to that audio on a green screen
  3. polls until each render is done, downloads the mp4
  4. chroma-keys green -> transparent webm (static ffmpeg with libvpx)
  5. uploads the webms to S3 and renders the episode with avatar overlays

Requires HEYGEN_API_KEY in the environment. Avatar chosen via --avatar-id
(list them with --list-avatars).

Usage:
  python scripts/heygen_avatar_test.py --list-avatars
  python scripts/heygen_avatar_test.py --date 2026-06-11 --avatar-id <id> --segments 2
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from ainews.config import load_config  # noqa: E402

PROJECT_ROOT = Path(__file__).parent.parent
RENDERER_DIR = PROJECT_ROOT / "renderer"
HEYGEN_BASE = "https://api.heygen.com"
GREEN = "#00b140"  # broadcast chroma green


def _client(api_key: str) -> httpx.Client:
    return httpx.Client(
        base_url=HEYGEN_BASE,
        headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
        timeout=60,
    )


def list_avatars(api_key: str) -> None:
    with _client(api_key) as c:
        r = c.get("/v2/avatars")
        r.raise_for_status()
        data = r.json().get("data", {})
        avatars = data.get("avatars", []) if isinstance(data, dict) else []
        print(f"{len(avatars)} avatars:")
        for a in avatars[:40]:
            print(f"  {a.get('avatar_id')}  {a.get('avatar_name')}  "
                  f"({a.get('gender','?')})")


def _s3():
    import boto3
    from botocore.config import Config
    return boto3.client("s3", region_name="us-east-1",
                        config=Config(retries={"max_attempts": 5, "mode": "adaptive"}))


def _upload_presigned(s3, bucket: str, local: Path, key: str, hours: int = 6) -> str:
    s3.upload_file(str(local), bucket, key)
    return s3.generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=hours * 3600)


def _submit(c: httpx.Client, avatar_id: str, audio_url: str) -> str:
    payload = {
        "video_inputs": [{
            "character": {"type": "avatar", "avatar_id": avatar_id,
                          "avatar_style": "normal"},
            "voice": {"type": "audio", "audio_url": audio_url},
            "background": {"type": "color", "value": GREEN},
        }],
        "dimension": {"width": 720, "height": 720},
    }
    r = c.post("/v2/video/generate", json=payload)
    r.raise_for_status()
    return r.json()["data"]["video_id"]


def _poll(c: httpx.Client, video_id: str, timeout_s: int = 900) -> str:
    started = time.monotonic()
    while time.monotonic() - started < timeout_s:
        r = c.get(f"/v1/video_status.get?video_id={video_id}")
        r.raise_for_status()
        d = r.json()["data"]
        status = d.get("status")
        if status == "completed":
            return d["video_url"]
        if status in ("failed", "error"):
            raise RuntimeError(f"HeyGen render failed: {d.get('error')}")
        time.sleep(15)
    raise TimeoutError(f"HeyGen video {video_id} not done in {timeout_s}s")


def _chroma_key(ffmpeg: str, mp4: Path, webm: Path) -> None:
    # Remove green -> alpha; encode VP9 with alpha so Remotion/Chromium composites it.
    subprocess.run([
        ffmpeg, "-y", "-i", str(mp4),
        "-vf", f"chromakey=0x00b140:0.13:0.06,format=yuva420p",
        "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-an", str(webm),
    ], check=True, capture_output=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-06-11")
    ap.add_argument("--avatar-id")
    ap.add_argument("--segments", type=int, default=2,
                    help="How many story segments (after cold open) get the avatar")
    ap.add_argument("--list-avatars", action="store_true")
    ap.add_argument("--ffmpeg", default="ffmpeg")
    args = ap.parse_args()

    api_key = os.environ.get("HEYGEN_API_KEY")
    if not api_key:
        print("ERROR: HEYGEN_API_KEY not set")
        sys.exit(1)

    if args.list_avatars:
        list_avatars(api_key)
        return
    if not args.avatar_id:
        print("ERROR: --avatar-id required (see --list-avatars)")
        sys.exit(1)

    date = args.date
    audio_dir = PROJECT_ROOT / "data" / "video_audio" / date
    manifest = json.loads((audio_dir / "manifest.json").read_text())
    # Sections to give an avatar: cold open + first N segments
    spoken = [s for s in manifest["sections"]
              if s["key"].endswith("cold_open") or s["key"][0:2].isdigit()]
    chosen = []
    seg_count = 0
    for s in manifest["sections"]:
        if s["key"].endswith("cold_open"):
            chosen.append(s)
        elif s["key"].endswith("sign_off"):
            continue
        elif seg_count < args.segments:
            chosen.append(s); seg_count += 1
    print(f"Avatar for {len(chosen)} sections: {[s['key'] for s in chosen]}")

    cfg = load_config()
    bucket = cfg.get("video", {}).get("assets_bucket", "ainews-render-assets")
    s3 = _s3()
    work = PROJECT_ROOT / "data" / "avatar_test" / date
    work.mkdir(parents=True, exist_ok=True)

    # 1+2: upload audio, submit all jobs (parallel HeyGen renders)
    jobs = {}
    with _client(api_key) as c:
        for s in chosen:
            audio_url = _upload_presigned(
                s3, bucket, audio_dir / s["audio"], f"avatar-audio/{date}/{s['audio']}")
            vid = _submit(c, args.avatar_id, audio_url)
            jobs[s["key"]] = vid
            print(f"  submitted {s['key']} -> {vid}")

        # 3: poll + download
        avatar_urls = {}
        for s in chosen:
            print(f"  polling {s['key']}...")
            url = _poll(c, jobs[s["key"]])
            mp4 = work / f"{s['key']}.mp4"
            mp4.write_bytes(httpx.get(url, timeout=120).content)
            # 4: chroma key
            webm = work / f"{s['key']}.webm"
            _chroma_key(args.ffmpeg, mp4, webm)
            # 5: upload webm
            avatar_urls[s["key"]] = _upload_presigned(
                s3, bucket, webm, f"avatar-webm/{date}/{webm.name}")
            print(f"  {s['key']} ready")

    # 6: build props with avatar overlays, render
    avatar_map_path = work / "avatar_urls.json"
    avatar_map_path.write_text(json.dumps(avatar_urls, indent=2))
    print(f"\nAvatar URLs written: {avatar_map_path}")
    print("Now render with: AVATAR_MAP=%s python generate_video.py --date %s "
          "(generate_video reads AVATAR_MAP to inject section.avatar)" % (avatar_map_path, date))


if __name__ == "__main__":
    main()
