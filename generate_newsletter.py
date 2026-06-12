#!/usr/bin/env python3
"""Compose and send the daily AI-news email newsletter.

Reuses the video pipeline's story selection (more stories) and the editorial
brief, renders an email-safe HTML issue, and sends it via Amazon SES to the
configured recipients.

Usage:
    python generate_newsletter.py --dry-run     # write HTML to disk, don't send
    python generate_newsletter.py               # compose + send
    python generate_newsletter.py --date 2026-06-11

Cron slot: a little after the episode renders, e.g. 19:20 UTC.
Configure under the `newsletter` key in config.yaml.
"""

import argparse
import logging
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

import anthropic

from ainews.config import load_config
from ainews.newsletter.compose import compose_newsletter, write_newsletter_json
from ainews.newsletter.render import render_html, render_text
from ainews.newsletter.send import send_newsletter
from ainews.storage.database import Database

PROJECT_ROOT = Path(__file__).parent


def main():
    parser = argparse.ArgumentParser(description="Compose and send the daily newsletter")
    parser.add_argument("--date", type=str, help="Issue date YYYY-MM-DD (default: today UTC)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Write HTML to data/newsletters/ and open it; do not send")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])
    log = logging.getLogger("newsletter")

    cfg = load_config()
    nl_cfg = cfg.get("newsletter", {})
    api_key = cfg.get("anthropic_api_key", "")
    if not api_key:
        print("ERROR: No Anthropic API key found.")
        sys.exit(1)

    data = PROJECT_ROOT / "data"
    newsletter_dir = data / "newsletters"
    scripts_dir = data / "video_scripts"

    db = Database(cfg["db_path"])
    client = anthropic.Anthropic(api_key=api_key)
    try:
        nl = compose_newsletter(
            db, client,
            newsletter_dir=newsletter_dir, scripts_dir=scripts_dir,
            on_date=args.date,
            min_score=nl_cfg.get("min_score", 6),
            max_stories=nl_cfg.get("max_stories", 12),
            site_url=nl_cfg.get("site_url", "https://ainews.eyrean.com"),
            logger_=log,
        )
    finally:
        db.close()

    if nl is None:
        print("No qualifying stories — no newsletter today.")
        return

    html = render_html(nl)
    text = render_text(nl)
    html_path = newsletter_dir / f"{nl['issue_date']}.html"
    newsletter_dir.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html, encoding="utf-8")
    print(f"Composed: {nl['subject']}")
    print(f"  {len(nl['stories'])} stories · saved {html_path.name}")

    if args.dry_run:
        # No archive JSON on dry runs — it would make these stories count as
        # "already covered" and starve the real send.
        print(f"\n✓ Dry run — preview: {html_path}")
        try:
            webbrowser.open(html_path.resolve().as_uri())
        except Exception:
            pass
        return

    # Archive the issue (drives day-to-day dedup) only when actually sending.
    json_path = write_newsletter_json(nl, newsletter_dir)
    print(f"  archived {json_path.name}")

    from_addr = nl_cfg.get("from_address")
    recipients = nl_cfg.get("recipients", [])
    if not from_addr or not recipients:
        print("ERROR: set newsletter.from_address and newsletter.recipients in config.yaml")
        sys.exit(1)

    result = send_newsletter(
        subject=nl["subject"], html=html, text=text,
        from_addr=from_addr, recipients=recipients,
        region=nl_cfg.get("ses_region", "us-west-1"),
        unsubscribe=nl_cfg.get("unsubscribe_address", from_addr),
        logger_=log,
    )
    print(f"\n✓ Sent to {len(result['sent'])}/{len(recipients)} recipients")
    if result["failed"]:
        print("  Failures:")
        for addr, err in result["failed"].items():
            print(f"    {addr}: {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
