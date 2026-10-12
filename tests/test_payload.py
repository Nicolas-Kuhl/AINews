"""Tests for the dashboard payload builder."""

from __future__ import annotations

import unittest

from ainews.dashboard.payload import _story_to_dict
from ainews.models import ProcessedNewsItem


def _item(url: str, title: str = "T") -> ProcessedNewsItem:
    return ProcessedNewsItem(id=1, title=title, url=url, source="Import AI", score=7)


class StoryLinkTests(unittest.TestCase):
    def test_non_http_urls_are_blanked_before_reaching_the_browser(self) -> None:
        story = _story_to_dict(
            _item("javascript:alert(document.cookie)"),
            [_item("newsletter://Import AI/abc/0", "Related")],
        )
        self.assertEqual(story["url"], "")
        self.assertEqual(story["related"][0]["url"], "")

    def test_http_urls_are_kept(self) -> None:
        story = _story_to_dict(_item("https://example.com/a"), [_item("https://b.example/x")])
        self.assertEqual(story["url"], "https://example.com/a")
        self.assertEqual(story["related"][0]["url"], "https://b.example/x")


if __name__ == "__main__":
    unittest.main()
