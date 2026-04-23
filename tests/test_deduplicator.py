import unittest

from ainews.models import RawNewsItem
from ainews.processing.deduplicator import deduplicate


class DeduplicatorVersionGuardTests(unittest.TestCase):
    def test_keeps_new_gpt_release_when_only_older_version_exists(self):
        items = [
            RawNewsItem(
                title="Introducing GPT-5.5",
                url="https://openai.com/index/introducing-gpt-5-5",
                source="OpenAI News",
            )
        ]

        unique, borderline = deduplicate(
            items,
            threshold=80,
            existing_titles=["introducing gpt-5.3-codex"],
            existing_urls=set(),
            borderline_low=50,
        )

        self.assertEqual([item.title for item in unique], ["Introducing GPT-5.5"])
        self.assertEqual(borderline, [])

    def test_keeps_new_system_card_when_older_system_card_exists(self):
        items = [
            RawNewsItem(
                title="GPT-5.5 System Card",
                url="https://openai.com/index/gpt-5-5-system-card",
                source="OpenAI News",
            )
        ]

        unique, borderline = deduplicate(
            items,
            threshold=80,
            existing_titles=["gpt-5.3-codex system card"],
            existing_urls=set(),
            borderline_low=50,
        )

        self.assertEqual([item.title for item in unique], ["GPT-5.5 System Card"])
        self.assertEqual(borderline, [])

    def test_still_deduplicates_same_release_title(self):
        items = [
            RawNewsItem(
                title="Introducing GPT-5.5",
                url="https://example.com/gpt-5-5",
                source="Example",
            )
        ]

        unique, _ = deduplicate(
            items,
            threshold=80,
            existing_titles=["introducing gpt-5.5"],
            existing_urls=set(),
            borderline_low=50,
        )

        self.assertEqual(unique, [])


if __name__ == "__main__":
    unittest.main()
