#!/usr/bin/env python3
"""Generate candidate 5-second musical intro stings via ElevenLabs.

One-off asset tool: renders several prompt variations into
data/voice_samples/stings/ for human audition. The chosen file should be
committed as renderer/public/branding/intro-sting.mp3 (bundled into the
Remotion site so Lambda renders can play it).

Requires ELEVENLABS_API_KEY in the environment.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx  # noqa: E402

PROMPTS = {
    "newsroom-pulse": (
        "Short 5-second modern news show intro sting: driving electronic pulse, "
        "rising synth arpeggio, punchy percussion hit at the end, energetic, clean finish"
    ),
    "tech-upbeat": (
        "Short 5-second upbeat tech podcast intro jingle: bright synth plucks, "
        "subtle glitch effects, optimistic, ends on a confident chord"
    ),
    "late-night-wry": (
        "Short 5-second playful late-night talk show sting: jazzy electric bass riff, "
        "snappy drums, a wink of brass, ends with a tight button"
    ),
    "minimal-ident": (
        "Short 5-second minimal broadcast ident: two warm marimba notes, soft whoosh, "
        "deep bass pulse, sleek and modern, clean ending"
    ),
}


def main():
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        print("ERROR: ELEVENLABS_API_KEY not set")
        sys.exit(1)

    out_dir = Path(__file__).parent.parent / "data" / "voice_samples" / "stings"
    out_dir.mkdir(parents=True, exist_ok=True)

    client = httpx.Client(
        base_url="https://api.elevenlabs.io/v1",
        headers={"xi-api-key": api_key},
        timeout=120,
    )
    for name, prompt in PROMPTS.items():
        resp = client.post("/sound-generation", json={
            "text": prompt,
            "duration_seconds": 5,
            "prompt_influence": 0.4,
        })
        if resp.status_code != 200:
            print(f"  {name}: FAILED ({resp.status_code}) {resp.text[:120]}")
            continue
        path = out_dir / f"sting-{name}.mp3"
        path.write_bytes(resp.content)
        print(f"  {path.name} ({len(resp.content) // 1024} KB)")

    print(f"\nCandidates in {out_dir}")


if __name__ == "__main__":
    main()
