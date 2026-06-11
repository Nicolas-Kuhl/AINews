#!/usr/bin/env python3
"""Generate the voiceover audio for an episode script.

Stage 2 of the video pipeline: reads the script JSON written by
generate_video_script.py and synthesizes per-section MP3s + word-level
speech marks with Amazon Polly (instance-role credentials, no API key).

Usage:
    python generate_voiceover.py                          # today's script
    python generate_voiceover.py --script data/video_scripts/2026-06-10.json
    python generate_voiceover.py --voice Matthew --engine generative
    python generate_voiceover.py --sample                 # audition voices
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from ainews.config import load_config
from ainews.video.tts import synthesize_samples, synthesize_script


def main():
    parser = argparse.ArgumentParser(description="Generate episode voiceover via Amazon Polly")
    parser.add_argument("--script", type=str, help="Path to episode script JSON (default: today's)")
    parser.add_argument("--voice", type=str, help="Polly voice id (e.g. Ruth, Matthew)")
    parser.add_argument("--engine", type=str, choices=["generative", "long-form", "neural", "standard"],
                        help="Polly engine")
    parser.add_argument("--region", type=str, help="AWS region for Polly")
    parser.add_argument("--output-dir", type=str, help="Base output directory")
    parser.add_argument("--sample", action="store_true",
                        help="Render a sample paragraph in several voices and exit")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])

    cfg = load_config()
    tts_cfg = cfg.get("tts", {})
    project_root = Path(__file__).parent
    voice = args.voice or tts_cfg.get("voice", "Ruth")
    engine = args.engine or tts_cfg.get("engine", "generative")
    region = args.region or tts_cfg.get("region", "us-east-1")
    base_dir = Path(args.output_dir or tts_cfg.get("output_dir") or
                    project_root / "data" / "video_audio")

    if args.sample:
        sample_dir = project_root / "data" / "voice_samples"
        written = synthesize_samples(sample_dir, region=region)
        print(f"\n✓ {len(written)} voice samples in {sample_dir}")
        for p in written:
            print(f"  {p.name}")
        return

    if args.script:
        script_path = Path(args.script)
    else:
        day_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        script_path = project_root / "data" / "video_scripts" / f"{day_key}.json"
    if not script_path.exists():
        print(f"ERROR: script not found: {script_path}")
        print("Run generate_video_script.py first.")
        sys.exit(1)

    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)

    episode_dir = base_dir / script_path.stem
    manifest = synthesize_script(
        script, episode_dir, voice=voice, engine=engine, region=region,
    )

    print()
    print(f"✓ Voiceover generated: {episode_dir}")
    print(f"  Sections:   {len(manifest['sections'])}")
    print(f"  Characters: {manifest['total_characters']}")
    total = manifest.get("total_duration_seconds")
    if total:
        print(f"  Duration:   {int(total // 60)}:{int(total % 60):02d}")
    print(f"  Voice:      {manifest['voice']} ({manifest['engine']})")


if __name__ == "__main__":
    main()
