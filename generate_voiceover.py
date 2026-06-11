#!/usr/bin/env python3
"""Generate the voiceover audio for an episode script.

Stage 2 of the video pipeline: reads the script JSON written by
generate_video_script.py and synthesizes per-section MP3s + word-level
timing marks. Default provider is ElevenLabs (ELEVENLABS_API_KEY env var);
falls back to Amazon Polly via instance-role credentials when no key is set.

Usage:
    python generate_voiceover.py                          # today's script
    python generate_voiceover.py --script data/video_scripts/2026-06-10.json
    python generate_voiceover.py --voice Charlie          # override voice
    python generate_voiceover.py --sample                 # audition voices
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from ainews.config import load_config
from ainews.video.tts import (
    ElevenLabsTTS,
    PollyTTS,
    POLLY_VOICE_CANDIDATES,
    make_tts,
    synthesize_samples,
    synthesize_script,
)


def _sample(cfg_tts: dict, sample_dir: Path) -> None:
    """Audition voices for the configured provider."""
    import os

    api_key = os.environ.get("ELEVENLABS_API_KEY") or cfg_tts.get("api_key")
    providers = []
    if api_key:
        # One probe client to list the account's voices, then a provider per voice
        lister = ElevenLabsTTS.__new__(ElevenLabsTTS)
        import httpx

        lister.http = httpx.Client(
            base_url="https://api.elevenlabs.io/v1",
            headers={"xi-api-key": api_key}, timeout=180,
        )
        voices = lister.list_voices()
        print(f"ElevenLabs account has {len(voices)} voices:")
        for v in voices:
            labels = ", ".join(f"{k}={val}" for k, val in v["labels"].items())
            print(f"  {v['name']:<16} {v['voice_id']}  {labels}")
        for v in voices:
            providers.append(ElevenLabsTTS(
                api_key, v["voice_id"], model_id=cfg_tts.get("model", "eleven_multilingual_v2"),
            ))
            providers[-1].label = f"{v['name']} (elevenlabs)"
    else:
        print("No ELEVENLABS_API_KEY — sampling Polly voices instead.")
        for voice, engine in POLLY_VOICE_CANDIDATES:
            providers.append(PollyTTS(voice=voice, engine=engine,
                                      region=cfg_tts.get("region", "us-east-1")))

    written = synthesize_samples(sample_dir, providers)
    print(f"\n✓ {len(written)} voice samples in {sample_dir}")
    for p in written:
        print(f"  {p.name}")


def main():
    parser = argparse.ArgumentParser(description="Generate episode voiceover")
    parser.add_argument("--script", type=str, help="Path to episode script JSON (default: today's)")
    parser.add_argument("--provider", type=str, choices=["elevenlabs", "polly"],
                        help="TTS provider (default from config)")
    parser.add_argument("--voice", type=str, help="Voice name or id")
    parser.add_argument("--output-dir", type=str, help="Base output directory")
    parser.add_argument("--sample", action="store_true",
                        help="Render a sample paragraph in the available voices and exit")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])

    cfg = load_config()
    tts_cfg = dict(cfg.get("tts", {}))
    if args.voice:
        tts_cfg["voice"] = args.voice
    project_root = Path(__file__).parent

    if args.sample:
        _sample(tts_cfg, project_root / "data" / "voice_samples")
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

    tts = make_tts(tts_cfg, provider=args.provider)
    base_dir = Path(args.output_dir or tts_cfg.get("output_dir") or
                    project_root / "data" / "video_audio")
    episode_dir = base_dir / script_path.stem
    manifest = synthesize_script(script, episode_dir, tts=tts)

    print()
    print(f"✓ Voiceover generated: {episode_dir}")
    print(f"  Sections:   {len(manifest['sections'])}")
    print(f"  Characters: {manifest['total_characters']}")
    total = manifest.get("total_duration_seconds")
    if total:
        print(f"  Duration:   {int(total // 60)}:{int(total % 60):02d}")
    print(f"  Voice:      {manifest['voice']}")


if __name__ == "__main__":
    main()
