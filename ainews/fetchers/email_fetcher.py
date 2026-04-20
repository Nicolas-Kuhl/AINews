"""Fetch news stories from email newsletters via IMAP."""

import email
import email.utils
from email.header import decode_header
import imaplib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import anthropic
import trafilatura

from ainews.models import RawNewsItem
from ainews.storage.database import Database

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """You are extracting individual news stories from an AI newsletter email.

The email is from "{newsletter_name}" with subject: "{subject}".

Analyze the email content below and extract each distinct news story or article mentioned.

For each story, provide:
- "title": A concise headline for the story (create one if not explicitly given)
- "url": The URL/link for the story if one is present, or null if it's inline content
- "description": A 2-3 sentence summary of what this story covers
- "content": For stories without a URL (essays/analysis), include the full text as presented in the email. For stories with URLs, leave this null.

Important:
- A single email may contain 1 to 20+ stories
- Some newsletters are curated link roundups (many stories with URLs)
- Some are essays or analyses (1-2 stories, often no external URLs)
- Some mix both formats
- Ignore navigation links, unsubscribe links, ads, social links, and footer content
- If the entire email is one essay/article, extract it as a single story

Respond with ONLY a JSON array, no other text.

EMAIL CONTENT:
{email_text}"""


@dataclass
class ParsedEmail:
    message_id: str
    sender: str
    subject: str
    date: Optional[datetime]
    html_body: str
    text_body: str


def fetch_all_newsletters(cfg: dict, db: Database) -> list[RawNewsItem]:
    """Fetch unread newsletter emails and extract stories using Claude.

    Args:
        cfg: Full application config dict (uses cfg["newsletters"] section)
        db: Database instance (for processed email tracking)

    Returns:
        List of RawNewsItem objects extracted from newsletters.
    """
    nl_cfg = cfg.get("newsletters", {})
    if not nl_cfg.get("enabled", False):
        return []

    imap_host = nl_cfg.get("imap_host", "imap.gmail.com")
    imap_port = nl_cfg.get("imap_port", 993)
    email_addr = nl_cfg.get("email", "")
    password = nl_cfg.get("password", "")

    if not email_addr or not password:
        logger.warning("  [Email] Missing email or password in config")
        return []

    senders = nl_cfg.get("senders", [])
    if not senders:
        logger.warning("  [Email] No newsletter senders configured")
        return []

    max_emails = nl_cfg.get("max_emails_per_run", 50)
    model = nl_cfg.get("model", cfg.get("model", "claude-sonnet-4-5-20250929"))

    # Connect to IMAP
    try:
        conn = _connect_imap(imap_host, imap_port, email_addr, password)
    except Exception as e:
        logger.error(f"  [Email] IMAP connection failed: {e}")
        return []

    all_items: list[RawNewsItem] = []
    client = anthropic.Anthropic(api_key=cfg.get("anthropic_api_key", ""))

    try:
        emails = _fetch_unread_emails(conn, max_emails)
        logger.info(f"  [Email] Found {len(emails)} unread emails")

        # Build sender lookup: address -> name
        sender_map = {}
        for s in senders:
            addr = s.get("address", "").lower()
            if addr:
                sender_map[addr] = s.get("name", addr)

        for uid, raw_bytes in emails:
            parsed = _parse_email(raw_bytes)
            if not parsed:
                continue

            # Check if already processed (idempotency)
            if db.is_email_processed(parsed.message_id):
                logger.info(f"  [Email] Skipping already processed: {parsed.subject}")
                continue

            # Filter to known senders
            newsletter_name = _match_sender(parsed.sender, sender_map)
            if not newsletter_name:
                continue

            logger.info(f"  [Email] Processing: {parsed.subject} (from {newsletter_name})")

            # Convert HTML to readable text
            email_text = _extract_text(parsed)
            if not email_text or len(email_text.strip()) < 50:
                logger.warning(f"  [Email] Empty/short content, skipping: {parsed.subject}")
                continue

            # Cap length to avoid token limits
            if len(email_text) > 30000:
                email_text = email_text[:30000] + "\n\n[Content truncated]"

            # Extract stories with Claude
            try:
                stories = _extract_stories_with_claude(
                    client, model, email_text, newsletter_name, parsed.subject
                )
            except Exception as e:
                logger.error(f"  [Email] Claude extraction failed for '{parsed.subject}': {e}")
                continue  # Don't mark as read — retry next run

            # Convert to RawNewsItems
            items = _stories_to_raw_items(
                stories, newsletter_name, parsed.message_id, parsed.date
            )
            all_items.extend(items)
            logger.info(f"  [Email] Extracted {len(items)} stories from '{parsed.subject}'")

            # Mark as processed in DB and Gmail
            db.mark_email_processed(
                parsed.message_id, parsed.sender, parsed.subject, len(items)
            )
            _mark_as_read(conn, uid)

    finally:
        try:
            conn.logout()
        except Exception:
            pass

    return all_items


def _connect_imap(host: str, port: int, email_addr: str, password: str) -> imaplib.IMAP4_SSL:
    """Connect and authenticate to IMAP server."""
    conn = imaplib.IMAP4_SSL(host, port)
    conn.login(email_addr, password)
    conn.select("INBOX")
    return conn


def _fetch_unread_emails(conn: imaplib.IMAP4_SSL, max_count: int) -> list[tuple[bytes, bytes]]:
    """Fetch unread emails from INBOX. Returns list of (uid, raw_bytes)."""
    status, data = conn.uid("search", None, "UNSEEN")
    if status != "OK" or not data[0]:
        return []

    uids = data[0].split()
    # Limit to max_count most recent
    uids = uids[-max_count:]

    results = []
    for uid in uids:
        status, msg_data = conn.uid("fetch", uid, "(RFC822)")
        if status == "OK" and msg_data[0]:
            results.append((uid, msg_data[0][1]))

    return results


def _parse_email(raw_bytes: bytes) -> Optional[ParsedEmail]:
    """Parse raw email bytes into a structured ParsedEmail."""
    try:
        msg = email.message_from_bytes(raw_bytes)
    except Exception:
        return None

    message_id = msg.get("Message-ID", "")
    sender = msg.get("From", "")
    subject = msg.get("Subject", "")
    # Decode subject if encoded
    if subject:
        decoded_parts = decode_header(subject)
        subject = "".join(
            part.decode(charset or "utf-8") if isinstance(part, bytes) else part
            for part, charset in decoded_parts
        )

    # Parse date
    date_str = msg.get("Date", "")
    parsed_date = None
    if date_str:
        try:
            parsed_tuple = email.utils.parsedate_to_datetime(date_str)
            parsed_date = parsed_tuple
        except Exception:
            pass

    # Extract body parts
    html_body = ""
    text_body = ""

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/html" and not html_body:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    html_body = payload.decode(charset, errors="replace")
            elif content_type == "text/plain" and not text_body:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    text_body = payload.decode(charset, errors="replace")
    else:
        content_type = msg.get_content_type()
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            if content_type == "text/html":
                html_body = decoded
            else:
                text_body = decoded

    return ParsedEmail(
        message_id=message_id,
        sender=sender,
        subject=subject,
        date=parsed_date,
        html_body=html_body,
        text_body=text_body,
    )


def _match_sender(from_header: str, sender_map: dict[str, str]) -> Optional[str]:
    """Match a From header against known senders. Returns newsletter name or None."""
    # Extract email address from "Name <addr>" format
    match = re.search(r"<([^>]+)>", from_header)
    addr = match.group(1).lower() if match else from_header.lower().strip()

    # Exact match
    if addr in sender_map:
        return sender_map[addr]

    # Domain match (e.g., anything@deeplearning.ai)
    domain = addr.split("@")[-1] if "@" in addr else ""
    for known_addr, name in sender_map.items():
        known_domain = known_addr.split("@")[-1] if "@" in known_addr else ""
        if domain and domain == known_domain:
            return name

    logger.info(f"  [Email] Skipping unrecognised sender: {addr}")
    return None


def _extract_text(parsed: ParsedEmail) -> str:
    """Convert email body to readable text. Prefers HTML (via trafilatura) over plaintext."""
    if parsed.html_body:
        try:
            text = trafilatura.extract(parsed.html_body, include_links=True)
            if text and len(text.strip()) > 50:
                return text
        except Exception:
            pass

    return parsed.text_body


def _extract_stories_with_claude(
    client: anthropic.Anthropic,
    model: str,
    email_text: str,
    newsletter_name: str,
    subject: str,
) -> list[dict]:
    """Use Claude to extract structured stories from newsletter text."""
    prompt = EXTRACTION_PROMPT.format(
        newsletter_name=newsletter_name,
        subject=subject,
        email_text=email_text,
    )

    response = client.messages.create(
        model=model,
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()

    # Handle markdown code fences
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)

    try:
        stories = json.loads(text)
    except json.JSONDecodeError:
        # Try to repair truncated JSON: close any open strings/arrays/objects
        repaired = _repair_json_array(text)
        stories = json.loads(repaired)

    if not isinstance(stories, list):
        stories = [stories]

    return stories


def _repair_json_array(text: str) -> str:
    """Attempt to repair a truncated JSON array from Claude.

    Common issue: max_tokens reached mid-string, leaving unterminated
    strings, objects, or the outer array bracket missing.
    """
    # Find the last complete object (ends with })
    last_brace = text.rfind("}")
    if last_brace == -1:
        raise json.JSONDecodeError("No complete JSON object found", text, 0)

    truncated = text[: last_brace + 1]

    # Close the array if needed
    if not truncated.rstrip().endswith("]"):
        truncated = truncated.rstrip().rstrip(",") + "\n]"

    return truncated


def _stories_to_raw_items(
    stories: list[dict],
    newsletter_name: str,
    message_id: str,
    email_date: Optional[datetime],
) -> list[RawNewsItem]:
    """Convert extracted story dicts to RawNewsItem objects."""
    items = []
    for i, story in enumerate(stories):
        title = story.get("title", "").strip()
        if not title:
            continue

        url = story.get("url") or ""
        url = url.strip() if url else ""

        # For stories without URLs, generate a synthetic one
        if not url:
            safe_id = re.sub(r"[^a-zA-Z0-9._-]", "", message_id.strip("<>"))
            url = f"newsletter://{newsletter_name}/{safe_id}#{i}"

        description = story.get("description", "")
        content = story.get("content")  # Full text for essay-style stories

        items.append(
            RawNewsItem(
                title=title,
                url=url,
                source=newsletter_name,
                published=email_date,
                description=description,
                content=content,
                fetched_via="newsletter",
            )
        )

    return items


def _mark_as_read(conn: imaplib.IMAP4_SSL, uid: bytes):
    """Mark an email as read in IMAP."""
    try:
        conn.uid("store", uid, "+FLAGS", "\\Seen")
    except Exception as e:
        logger.warning(f"  [Email] Failed to mark email as read: {e}")
