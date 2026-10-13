"""Fetch news stories from email newsletters via IMAP."""

import email
import email.utils
from email.header import decode_header
import hashlib
import imaplib
import json
import logging
import re
import ssl
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import anthropic
import trafilatura

from ainews import llm
from ainews.models import RawNewsItem
from ainews.storage.database import Database

logger = logging.getLogger(__name__)

# Room for adaptive thinking plus 20+ stories (non-streaming cap).
EXTRACTION_MAX_TOKENS = 16000

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
    model = llm.model_for(cfg, "newsletter_extraction")
    effort = llm.effort_for(cfg, "newsletter_extraction")

    # Connect to IMAP
    try:
        conn = _connect_imap(imap_host, imap_port, email_addr, password)
    except Exception as e:
        logger.error(f"  [Email] IMAP connection failed: {e}")
        return []

    all_items: list[RawNewsItem] = []
    client = anthropic.Anthropic(api_key=cfg.get("anthropic_api_key", ""))

    try:
        emails = _fetch_unread_emails(conn, max_emails, _sender_search_terms(senders))
        logger.info(f"  [Email] Found {len(emails)} unread newsletter emails")

        # Build sender lookup: address -> name
        sender_map = {}
        for s in senders:
            addr = s.get("address", "").lower()
            if addr:
                sender_map[addr] = s.get("name", addr)

        for uid, raw_bytes in emails:
            # One malformed email or odd model response must not abort the
            # whole daily run; it stays unread and unprocessed for a retry.
            try:
                items = _process_email(
                    conn, db, client, model, uid, raw_bytes, sender_map, effort
                )
            except Exception as e:  # noqa: BLE001
                logger.error(f"  [Email] Failed to process email uid={uid!r}: {e}")
                continue
            all_items.extend(items)

    except Exception as e:  # noqa: BLE001 — IMAP search/fetch errors (timeouts)
        logger.error(f"  [Email] IMAP error, keeping {len(all_items)} items so far: {e}")
    finally:
        try:
            conn.logout()
        except Exception:
            pass

    return all_items


def _process_email(
    conn: imaplib.IMAP4_SSL,
    db: Database,
    client: anthropic.Anthropic,
    model: str,
    uid: bytes,
    raw_bytes: bytes,
    sender_map: dict[str, str],
    effort: str = llm.DEFAULT_EFFORT["newsletter_extraction"],
) -> list[RawNewsItem]:
    """Extract stories from one email; marks it processed only on success."""
    parsed = _parse_email(raw_bytes)
    if not parsed:
        return []

    # Check if already processed (idempotency)
    if db.is_email_processed(parsed.message_id):
        logger.info(f"  [Email] Skipping already processed: {parsed.subject}")
        return []

    # Filter to known senders
    newsletter_name = _match_sender(parsed.sender, sender_map)
    if not newsletter_name:
        return []

    logger.info(f"  [Email] Processing: {parsed.subject} (from {newsletter_name})")

    # Convert HTML to readable text
    email_text = _extract_text(parsed)
    if not email_text or len(email_text.strip()) < 50:
        # Deterministic: it will never have content, so record it as done
        # rather than re-downloading it on every run.
        logger.warning(f"  [Email] Empty/short content, skipping: {parsed.subject}")
        db.mark_email_processed(parsed.message_id, parsed.sender, parsed.subject, 0)
        _mark_as_read(conn, uid)
        return []

    # Cap length to avoid token limits
    if len(email_text) > 30000:
        email_text = email_text[:30000] + "\n\n[Content truncated]"

    # Extract stories with Claude (raises -> caller leaves it unread for retry)
    stories = _extract_stories_with_claude(
        client, model, email_text, newsletter_name, parsed.subject, effort
    )
    items = _stories_to_raw_items(stories, newsletter_name, parsed.message_id, parsed.date)
    logger.info(f"  [Email] Extracted {len(items)} stories from '{parsed.subject}'")

    # Mark as processed in DB and Gmail
    db.mark_email_processed(parsed.message_id, parsed.sender, parsed.subject, len(items))
    _mark_as_read(conn, uid)
    return items


IMAP_TIMEOUT_SECONDS = 30


def _connect_imap(host: str, port: int, email_addr: str, password: str) -> imaplib.IMAP4_SSL:
    """Connect and authenticate to IMAP server.

    Uses a verifying TLS context: without one, ``IMAP4_SSL`` falls back to an
    unverified context and the app password would go to whoever answers.
    """
    conn = imaplib.IMAP4_SSL(
        host, port,
        ssl_context=ssl.create_default_context(),
        timeout=IMAP_TIMEOUT_SECONDS,
    )
    conn.login(email_addr, password)
    conn.select("INBOX")
    return conn


def _sender_search_terms(senders: list[dict]) -> list[str]:
    """Unique sender domains to search for — mirrors _match_sender's domain match."""
    domains = {
        s.get("address", "").strip().lower().split("@")[-1]
        for s in senders
        if "@" in s.get("address", "")
    }
    return sorted(d for d in domains if d)


def _fetch_unread_emails(
    conn: imaplib.IMAP4_SSL, max_count: int, sender_terms: list[str]
) -> list[tuple[bytes, bytes]]:
    """Fetch unread emails from known senders. Returns list of (uid, raw_bytes).

    The search runs server-side per sender domain, so unrelated mail in the
    inbox is never downloaded, and messages are fetched with BODY.PEEK[] so
    fetching never sets \\Seen — only a successfully processed newsletter is
    marked read (by _mark_as_read), and a failed one is retried next run.
    """
    uids: set[bytes] = set()
    for term in sender_terms:
        status, data = conn.uid("search", None, "UNSEEN", "FROM", f'"{term}"')
        if status == "OK" and data and data[0]:
            uids.update(data[0].split())

    # Limit to max_count most recent (UIDs increase with arrival)
    ordered = sorted(uids, key=int)[-max_count:]

    results = []
    for uid in ordered:
        status, msg_data = conn.uid("fetch", uid, "(BODY.PEEK[])")
        if status == "OK" and msg_data and isinstance(msg_data[0], tuple):
            results.append((uid, msg_data[0][1]))

    return results


def _decode_subject(subject: str) -> str:
    """Decode an RFC 2047 subject; unknown or broken charsets degrade to
    replacement characters instead of raising."""
    if not subject:
        return ""
    parts = []
    for part, charset in decode_header(subject):
        if isinstance(part, bytes):
            try:
                parts.append(part.decode(charset or "utf-8", errors="replace"))
            except LookupError:
                parts.append(part.decode("utf-8", errors="replace"))
        else:
            parts.append(part)
    return "".join(parts)


def _decode_payload(payload: bytes, charset: Optional[str]) -> str:
    try:
        return payload.decode(charset or "utf-8", errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _parse_email(raw_bytes: bytes) -> Optional[ParsedEmail]:
    """Parse raw email bytes into a structured ParsedEmail."""
    try:
        msg = email.message_from_bytes(raw_bytes)
    except Exception:
        return None

    # Processed-email idempotency keys on this, so an email without a
    # Message-ID gets a stable content hash rather than "" (which would make
    # every later ID-less email look already processed).
    message_id = (msg.get("Message-ID") or "").strip()
    if not message_id:
        message_id = "<sha256:" + hashlib.sha256(raw_bytes).hexdigest() + ">"
    sender = str(msg.get("From", ""))
    subject = _decode_subject(str(msg.get("Subject", "")))

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
                    html_body = _decode_payload(payload, part.get_content_charset())
            elif content_type == "text/plain" and not text_body:
                payload = part.get_payload(decode=True)
                if payload:
                    text_body = _decode_payload(payload, part.get_content_charset())
    else:
        content_type = msg.get_content_type()
        payload = msg.get_payload(decode=True)
        if payload:
            decoded = _decode_payload(payload, msg.get_content_charset())
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
    effort: str = llm.DEFAULT_EFFORT["newsletter_extraction"],
) -> list[dict]:
    """Use Claude to extract structured stories from newsletter text."""
    prompt = EXTRACTION_PROMPT.format(
        newsletter_name=newsletter_name,
        subject=subject,
        email_text=email_text,
    )

    response = llm.create(
        client, model=model, effort=effort, max_tokens=EXTRACTION_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    # A long essay can run past max_tokens; the complete stories before the
    # cut are still worth keeping (_repair_json_array below).
    text = llm.response_text(response, allow_truncated=True).strip()

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
            # Index in the path, not a #fragment: normalize_url strips
            # fragments, which collapsed every URL-less story in an email
            # onto one URL and deduped all but the first away.
            safe_id = re.sub(r"[^a-zA-Z0-9._-]", "", message_id.strip("<>"))
            url = f"newsletter://{newsletter_name}/{safe_id}/{i}"

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
