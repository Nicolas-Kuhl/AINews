"""Tests for the editorial brief generator."""

from __future__ import annotations

import unittest

from ainews import llm
from ainews.models import ProcessedNewsItem
from ainews.processing import brief
from claude_fakes import FakeClaude


def _story(n: int) -> ProcessedNewsItem:
    return ProcessedNewsItem(title=f"Story {n}", url=f"https://x/{n}", source="S",
                             summary=f"Summary {n}.", score=9 - n)


class BriefTests(unittest.TestCase):
    def test_brief_text_is_read_after_a_thinking_block(self) -> None:
        client = FakeClaude("Morning Brief: **Lab** shipped a model.")
        out = brief.generate_morning_brief(client, [_story(1), _story(2)])
        self.assertEqual(out, "**Lab** shipped a model.")

    def test_brief_request_uses_the_task_model_with_room_to_think(self) -> None:
        client = FakeClaude("A paragraph.")
        brief.generate_day_brief(client, [_story(1)])
        req = client.requests[0]
        self.assertEqual(req["model"], llm.DEFAULT_MODELS["brief"])
        self.assertEqual(req["output_config"], {"effort": llm.DEFAULT_EFFORT["brief"]})
        # 600 tokens was sized for no thinking; thinking now counts toward it.
        self.assertGreaterEqual(req["max_tokens"], 4000)


if __name__ == "__main__":
    unittest.main()
