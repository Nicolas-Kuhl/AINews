#!/usr/bin/env python3
"""Compose and send the daily AI-news email newsletter.

Reuses the video pipeline's story selection (more stories) and the editorial
brief, renders an email-safe HTML issue, and sends it via Amazon SES to the
configured recipients.

Usage:
    python generate_newsletter.py --dry-run     # write HTML to disk, don't send
    python generate_newsletter.py               # compose + send
    python generate_newsletter.py --date 2026-06-11

Re-running is safe: once an issue is archived it is re-rendered rather than
recomposed, and recipients recorded in data/newsletters/<date>.sent are
skipped — so a rerun after a partial failure only sends the same issue to
the recipients who didn't get it.

Cron slot: a little after the episode renders, e.g. 19:20 UTC.
Configure under the `newsletter` key in config.yaml.
"""

import argparse
import logging
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import anthropic

from ainews.config import load_config
from ainews.newsletter.compose import (
    compose_newsletter,
    load_archived_issue,
    write_newsletter_json,
)
from ainews.newsletter.render import render_html, render_text
from ainews.newsletter.send import load_sent, record_sent, send_newsletter, sent_ledger_path
from ainews.storage.database import Database

PROJECT_ROOT = Path(__file__).parent


def run(
    cfg: dict,
    *,
    db: Database,
    client,
    data_dir: Path,
    on_date: Optional[str],
    dry_run: bool,
    ses_client=None,
    log: Optional[logging.Logger] = None,
) -> int:
    """Compose (or reuse) the issue and send it. Returns a process exit code."""
    log = log or logging.getLogger("newsletter")
    nl_cfg = cfg.get("newsletter", {})
    newsletter_dir = data_dir / "newsletters"
    scripts_dir = data_dir / "video_scripts"
    issue_date = on_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Check sending config before anything is archived: the archive marks
    # the stories as covered, so archiving an unsent issue would starve it.
    from_addr = nl_cfg.get("from_address")
    recipients = nl_cfg.get("recipients", [])
    if not dry_run and (not from_addr or not recipients):
        print("ERROR: set newsletter.from_address and newsletter.recipients in config.yaml")
        return 2

    nl = load_archived_issue(newsletter_dir, issue_date)
    archived = nl is not None
    if archived:
        print(f"Reusing the archived {issue_date} issue (already composed)")
    else:
        nl = compose_newsletter(
            db, client,
            newsletter_dir=newsletter_dir, scripts_dir=scripts_dir,
            on_date=on_date,
            min_score=nl_cfg.get("min_score", 6),
            max_stories=nl_cfg.get("max_stories", 12),
            site_url=nl_cfg.get("site_url", "https://ainews.eyrean.com"),
            logger_=log,
        )
    if nl is None:
        print("No qualifying stories — no newsletter today.")
        return 0

    html = render_html(nl)
    text = render_text(nl)
    html_path = newsletter_dir / f"{nl['issue_date']}.html"
    newsletter_dir.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html, encoding="utf-8")
    print(f"Composed: {nl['subject']}")
    print(f"  {len(nl['stories'])} stories · saved {html_path.name}")

    if dry_run:
        # No archive JSON on dry runs — it would make these stories count as
        # "already covered" and starve the real send.
        print(f"\n✓ Dry run — preview: {html_path}")
        try:
            webbrowser.open(html_path.resolve().as_uri())
        except Exception:
            pass
        return 0

    if not archived:
        json_path = write_newsletter_json(nl, newsletter_dir)
        print(f"  archived {json_path.name}")

    ledger = sent_ledger_path(newsletter_dir, nl["issue_date"])
    already = load_sent(ledger)
    pending = [r for r in recipients if r not in already]
    if not pending:
        print(f"\n✓ Already sent to all {len(recipients)} recipients — nothing to do")
        return 0
    if already:
        print(f"  {len(already)} recipient(s) already have this issue; sending to {len(pending)}")

    result = send_newsletter(
        subject=nl["subject"], html=html, text=text,
        from_addr=from_addr, recipients=pending,
        region=nl_cfg.get("ses_region", "us-west-1"),
        unsubscribe=nl_cfg.get("unsubscribe_address", from_addr),
        ses_client=ses_client,
        on_sent=lambda addr: record_sent(ledger, addr),
        logger_=log,
    )
    print(f"\n✓ Sent to {len(result['sent'])}/{len(pending)} recipients")
    if result["failed"]:
        print("  Failures (re-run to retry just these):")
        for addr, err in result["failed"].items():
            print(f"    {addr}: {err}")
        return 1
    return 0


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
    api_key = cfg.get("anthropic_api_key", "")
    if not api_key:
        print("ERROR: No Anthropic API key found.")
        sys.exit(1)

    db = Database(cfg["db_path"])
    try:
        code = run(
            cfg, db=db, client=anthropic.Anthropic(api_key=api_key),
            data_dir=PROJECT_ROOT / "data", on_date=args.date,
            dry_run=args.dry_run, log=log,
        )
    finally:
        db.close()
    sys.exit(code)


if __name__ == "__main__":
    main()
