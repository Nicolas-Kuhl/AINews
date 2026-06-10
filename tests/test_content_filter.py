"""Tests for the pre-scoring junk filter."""

from __future__ import annotations

import unittest

from ainews.models import RawNewsItem
from ainews.processing.content_filter import filter_junk, is_junk


def _item(title: str, url: str = "https://example.com/a", source: str = "X") -> RawNewsItem:
    return RawNewsItem(title=title, url=url, source=source)


class ContentFilterTests(unittest.TestCase):
    def test_drops_horoscope_titles(self) -> None:
        cases = [
            "Gemini horoscope today for June 8, 2026: A workplace rivalry…",
            "Gemini June 2026 monthly horoscope: Maintain harmony…",
            "Daily astrology forecast for Leos",
            "Capricorn zodiac sign and you",
        ]
        for t in cases:
            ok, reason = is_junk(_item(t))
            self.assertTrue(ok, f"should drop: {t!r} (reason: {reason})")

    def test_keeps_ai_titles_that_mention_zodiac_words(self) -> None:
        """Critical: 'Gemini' as a Google model name must not be dropped."""
        cases = [
            "Google launches Gemini 3 Pro",
            "Gemini news roundup — what shipped this week",
            "Anthropic ships Claude 4.8",
            "OpenAI rolls out Codex updates",
            "Gemini API adds tool-use streaming",
        ]
        for t in cases:
            ok, reason = is_junk(_item(t))
            self.assertFalse(ok, f"should KEEP: {t!r} (got reason: {reason})")

    def test_drops_lifestyle_leak(self) -> None:
        cases = [
            "Capricorn love life forecast",
            "Rashifal today: what the stars say",
        ]
        for t in cases:
            ok, _ = is_junk(_item(t))
            self.assertTrue(ok, f"should drop: {t!r}")

    def test_filter_junk_partitions(self) -> None:
        items = [
            _item("Gemini horoscope today for June 8"),
            _item("Google launches Gemini 3 Pro"),
            _item("Daily horoscope: Leo"),
            _item("Anthropic ships Claude 4.8"),
        ]
        kept, dropped = filter_junk(items)
        self.assertEqual(len(kept), 2)
        self.assertEqual(len(dropped), 2)
        self.assertEqual(
            {item.title for item, _ in dropped},
            {"Gemini horoscope today for June 8", "Daily horoscope: Leo"},
        )


if __name__ == "__main__":
    unittest.main()
