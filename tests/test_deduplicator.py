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


class ParseFirstJsonArrayTests(unittest.TestCase):
    """Robust parsing of model responses that should be a bare JSON array."""

    def test_plain_array(self):
        from ainews.processing.deduplicator import parse_first_json_array
        self.assertEqual(parse_first_json_array("[1, 3, 7]"), [1, 3, 7])

    def test_empty_array(self):
        from ainews.processing.deduplicator import parse_first_json_array
        self.assertEqual(parse_first_json_array("[]"), [])

    def test_prose_before_array(self):
        from ainews.processing.deduplicator import parse_first_json_array
        text = (
            "Looking at each pair, I need to identify articles about the same "
            "specific event.\n\nLet me analyze them.\n\n[2, 5]"
        )
        self.assertEqual(parse_first_json_array(text), [2, 5])

    def test_bracket_noise_in_prose_before_real_array(self):
        from ainews.processing.deduplicator import parse_first_json_array
        # The old greedy regex spanned from the first '[' to the last ']' and
        # failed; the decoder-based parse skips the non-JSON bracket.
        text = "Pairs [like these] need care.\nAnswer: [1, 4]"
        self.assertEqual(parse_first_json_array(text), [1, 4])

    def test_cluster_of_clusters(self):
        from ainews.processing.deduplicator import parse_first_json_array
        self.assertEqual(parse_first_json_array("[[1, 2], [3]]"), [[1, 2], [3]])

    def test_fenced_array(self):
        from ainews.processing.deduplicator import parse_first_json_array
        self.assertEqual(parse_first_json_array("```json\n[9]\n```"), [9])

    def test_trailing_prose_after_array(self):
        from ainews.processing.deduplicator import parse_first_json_array
        self.assertEqual(parse_first_json_array("[6]\n\nThese match because..."), [6])

    def test_no_array_raises(self):
        from ainews.processing.deduplicator import parse_first_json_array
        with self.assertRaises(ValueError):
            parse_first_json_array("I could not find any matching pairs.")
