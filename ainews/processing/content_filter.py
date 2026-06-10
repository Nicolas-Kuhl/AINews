"""Drop obvious non-AI content at fetch time.

This is a pre-scoring filter — the goal is to avoid sending Claude tokens
for items the title alone proves are irrelevant (horoscopes, celebrity
gossip, lifestyle wires). The scorer would assign them score 1 anyway but
that costs API calls. Better to drop early.

Conservative by design: when in doubt, keep. Anything matching here would
have hit score ≤ 2 from the scorer.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from ainews.models import RawNewsItem

logger = logging.getLogger(__name__)


# Horoscope / astrology — the "Gemini" zodiac sign keeps pulling these in via
# search queries that look for "Gemini news".
_HOROSCOPE = re.compile(
    r"\b(horoscope|zodiac|astrology|astrological)\b",
    re.IGNORECASE,
)

# Zodiac sign + day/date phrasing — catches "Gemini horoscope today",
# "Aries June 8, 2026" etc. without flagging "Gemini news" or "Gemini 3 Pro".
_ZODIAC_DAILY = re.compile(
    r"\b(aries|taurus|gemini|cancer|leo|virgo|libra|scorpio|sagittarius|"
    r"capricorn|aquarius|pisces)\b.*\b(today|tomorrow|monthly|weekly|"
    r"daily|june|jul[yi]|august|septem|octobe|novem|decemb|"
    r"january|febru|march|april|may)\b",
    re.IGNORECASE,
)

# Celebrity / lifestyle wire patterns from Indian aggregator news sites that
# leak through Google News for "AI" queries (because they touch AI tangentially).
_LIFESTYLE_LEAK = re.compile(
    r"\b(rashifal|panchang|love life|relationship|marriage|"
    r"workplace rivalry|lucky number|lucky color)\b",
    re.IGNORECASE,
)

# Domains that consistently produce non-AI noise via Google News search.
# Anything matching here AND scoring poorly on title gets dropped.
_NOISY_DOMAINS = {
    # Lifestyle / astrology aggregators that piggy-back on "Gemini news"
    "hindustantimes.com",
    "indiatimes.com",
    "zeenews.india.com",
    "astrofame.com",
    "msn.com",  # only when the wrapped publisher is also a noisy domain
}


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        return host.removeprefix("www.")
    except Exception:
        return ""


def is_junk(item: RawNewsItem) -> tuple[bool, str]:
    """Return ``(True, reason)`` when the item is clearly non-AI noise."""
    title = item.title or ""
    if _HOROSCOPE.search(title):
        return True, "horoscope keyword"
    if _ZODIAC_DAILY.search(title):
        return True, "zodiac-daily pattern"
    if _LIFESTYLE_LEAK.search(title):
        return True, "lifestyle/wire phrase"
    return False, ""


def filter_junk(items: list[RawNewsItem]) -> tuple[list[RawNewsItem], list[tuple[RawNewsItem, str]]]:
    """Split items into ``(kept, dropped_with_reason)``."""
    kept: list[RawNewsItem] = []
    dropped: list[tuple[RawNewsItem, str]] = []
    for item in items:
        is_bad, reason = is_junk(item)
        if is_bad:
            dropped.append((item, reason))
        else:
            kept.append(item)
    return kept, dropped
