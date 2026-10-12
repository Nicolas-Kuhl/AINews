"""Send the rendered newsletter via Amazon SES (instance-role credentials).

Sends a single multipart (HTML + text) message. For a small known list we
send one message per recipient (so each gets a clean To: line and we can
honor a per-recipient List-Unsubscribe later). Includes the List-Unsubscribe
header that Gmail/Yahoo now expect even from small senders.
"""

from __future__ import annotations

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def sent_ledger_path(newsletter_dir: Path, issue_date: str) -> Path:
    """Append-only record of recipients who already received an issue."""
    return Path(newsletter_dir) / f"{issue_date}.sent"


def load_sent(ledger: Path) -> "set[str]":
    if not ledger.exists():
        return set()
    return {line.strip() for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()}


def record_sent(ledger: Path, address: str) -> None:
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with open(ledger, "a", encoding="utf-8") as f:
        f.write(address + "\n")


def _build_message(subject: str, html: str, text: str, from_addr: str,
                   to_addr: str, unsubscribe: Optional[str]) -> "MIMEMultipart":
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    if unsubscribe:
        msg["List-Unsubscribe"] = f"<mailto:{unsubscribe}?subject=unsubscribe>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    return msg


def send_newsletter(
    *,
    subject: str,
    html: str,
    text: str,
    from_addr: str,
    recipients: "list[str]",
    region: str = "us-west-1",
    unsubscribe: Optional[str] = None,
    ses_client=None,
    on_sent: Optional[Callable[[str], None]] = None,
    logger_: Optional[logging.Logger] = None,
) -> dict:
    """Send to each recipient. Returns {sent: [...], failed: {addr: error}}.

    ``on_sent(addr)`` runs right after each successful send, so a crash
    mid-list still leaves an accurate record of who already has the issue.
    """
    log = logger_ or logger
    if ses_client is None:
        import boto3
        ses_client = boto3.client("ses", region_name=region)

    sent, failed = [], {}
    for to_addr in recipients:
        msg = _build_message(subject, html, text, from_addr, to_addr, unsubscribe)
        try:
            ses_client.send_raw_email(
                Source=from_addr,
                Destinations=[to_addr],
                RawMessage={"Data": msg.as_string()},
            )
            sent.append(to_addr)
            log.info("Newsletter sent to %s", to_addr)
            if on_sent:
                on_sent(to_addr)
        except Exception as exc:  # noqa: BLE001
            failed[to_addr] = str(exc)
            log.warning("Newsletter send failed for %s: %s", to_addr, exc)
    return {"sent": sent, "failed": failed}
