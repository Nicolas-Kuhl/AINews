"""Tests for newsletter IMAP ingestion (no network: IMAP is faked)."""

from __future__ import annotations

import ssl
import unittest
from unittest import mock

from ainews.fetchers import email_fetcher
from ainews.processing.deduplicator import normalize_url


class _FakeImap:
    """Records UID commands; SEARCH answers from a criteria -> uids map."""

    def __init__(self, search_results: dict[str, bytes], bodies: dict[bytes, bytes]):
        self.search_results = search_results
        self.bodies = bodies
        self.commands: list[tuple] = []

    def uid(self, command, *args):
        self.commands.append((command, *args))
        if command == "search":
            criteria = " ".join(a for a in args if a)
            return "OK", [self.search_results.get(criteria, b"")]
        if command == "fetch":
            uid, spec = args
            return "OK", [(b"1 (UID " + uid + b" BODY[] {10}", self.bodies[uid]), b")"]
        return "OK", [None]


class ConnectImapTests(unittest.TestCase):
    def test_connects_with_verified_tls_and_a_timeout(self) -> None:
        with mock.patch.object(email_fetcher.imaplib, "IMAP4_SSL") as imap_cls:
            email_fetcher._connect_imap("imap.example.com", 993, "me@example.com", "pw")
        _, kwargs = imap_cls.call_args
        ctx = kwargs.get("ssl_context")
        self.assertIsNotNone(ctx, "IMAP4_SSL must get an explicit ssl_context")
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)
        self.assertTrue(kwargs.get("timeout"))


class FetchUnreadEmailsTests(unittest.TestCase):
    def test_fetch_peeks_so_messages_are_not_marked_read(self) -> None:
        conn = _FakeImap({'UNSEEN FROM "news.example.com"': b"7"}, {b"7": b"raw"})
        email_fetcher._fetch_unread_emails(conn, 10, ["news.example.com"])
        fetches = [c for c in conn.commands if c[0] == "fetch"]
        self.assertEqual(fetches, [("fetch", b"7", "(BODY.PEEK[])")])

    def test_only_messages_from_known_senders_are_fetched(self) -> None:
        conn = _FakeImap(
            {'UNSEEN FROM "a.example"': b"3 9", 'UNSEEN FROM "b.example"': b"5"},
            {b"3": b"three", b"5": b"five", b"9": b"nine"},
        )
        results = email_fetcher._fetch_unread_emails(conn, 10, ["a.example", "b.example"])
        self.assertEqual([uid for uid, _ in results], [b"3", b"5", b"9"])
        self.assertEqual([raw for _, raw in results], [b"three", b"five", b"nine"])

    def test_max_count_keeps_the_newest_messages(self) -> None:
        conn = _FakeImap({'UNSEEN FROM "a.example"': b"1 2 3"},
                         {b"2": b"two", b"3": b"three"})
        results = email_fetcher._fetch_unread_emails(conn, 2, ["a.example"])
        self.assertEqual([uid for uid, _ in results], [b"2", b"3"])


class SenderSearchTermsTests(unittest.TestCase):
    def test_search_terms_are_unique_sender_domains(self) -> None:
        terms = email_fetcher._sender_search_terms(
            [{"address": "News@TLDR.tech"}, {"address": "dan@tldr.tech"},
             {"address": "importai@substack.com"}, {"address": ""}]
        )
        self.assertEqual(terms, ["substack.com", "tldr.tech"])


class ParseEmailTests(unittest.TestCase):
    def test_unknown_subject_charset_does_not_raise(self) -> None:
        raw = (b"Message-ID: <a@x>\r\nFrom: n@x.com\r\n"
               b"Subject: =?x-bogus-charset?q?Hello?=\r\n\r\nbody text")
        parsed = email_fetcher._parse_email(raw)
        self.assertIsNotNone(parsed)
        self.assertIn("Hello", parsed.subject)

    def test_missing_message_id_gets_a_stable_content_hash(self) -> None:
        raw_a = b"From: n@x.com\r\nSubject: A\r\n\r\nbody a"
        raw_b = b"From: n@x.com\r\nSubject: B\r\n\r\nbody b"
        a1 = email_fetcher._parse_email(raw_a).message_id
        a2 = email_fetcher._parse_email(raw_a).message_id
        b = email_fetcher._parse_email(raw_b).message_id
        self.assertTrue(a1)
        self.assertEqual(a1, a2)
        self.assertNotEqual(a1, b)


def _email(msg_id: str, subject: str) -> bytes:
    body = "Story text that is long enough to pass the minimum length check. " * 3
    return (f"Message-ID: <{msg_id}@x>\r\nFrom: Newsletter <news@a.example>\r\n"
            f"Subject: {subject}\r\nContent-Type: text/plain\r\n\r\n{body}").encode()


class FetchAllNewslettersTests(unittest.TestCase):
    def setUp(self) -> None:
        import os
        import tempfile
        from ainews.storage.database import Database
        self.db = Database(os.path.join(tempfile.mkdtemp(), "t.db"))
        self.cfg = {
            "anthropic_api_key": "sk-test",
            "newsletters": {
                "enabled": True, "email": "me@x.com", "password": "pw",
                "senders": [{"address": "news@a.example", "name": "A News"}],
            },
        }

    def tearDown(self) -> None:
        self.db.close()

    def test_one_bad_email_does_not_abort_the_rest(self) -> None:
        conn = _FakeImap({'UNSEEN FROM "a.example"': b"1 2"},
                         {b"1": _email("bad", "Bad"), b"2": _email("good", "Good")})

        def extract(client, model, text, name, subject):
            if subject == "Bad":
                return ["not a story object"]
            return [{"title": "Real story", "url": "https://a.example/s", "description": "d"}]

        with mock.patch.object(email_fetcher, "_connect_imap", return_value=conn), \
             mock.patch.object(email_fetcher, "_extract_stories_with_claude", side_effect=extract):
            items = email_fetcher.fetch_all_newsletters(self.cfg, self.db)

        self.assertEqual([i.title for i in items], ["Real story"])
        self.assertFalse(self.db.is_email_processed("<bad@x>"))
        self.assertTrue(self.db.is_email_processed("<good@x>"))

    def test_too_short_email_is_marked_done_instead_of_refetched_daily(self) -> None:
        short = (b"Message-ID: <short@x>\r\nFrom: Newsletter <news@a.example>\r\n"
                 b"Subject: Hi\r\nContent-Type: text/plain\r\n\r\ntiny")
        conn = _FakeImap({'UNSEEN FROM "a.example"': b"1"}, {b"1": short})
        with mock.patch.object(email_fetcher, "_connect_imap", return_value=conn), \
             mock.patch.object(email_fetcher, "_extract_stories_with_claude") as extract:
            items = email_fetcher.fetch_all_newsletters(self.cfg, self.db)
        self.assertEqual(items, [])
        extract.assert_not_called()
        self.assertTrue(self.db.is_email_processed("<short@x>"))
        self.assertIn(("store", b"1", "+FLAGS", "\\Seen"), conn.commands)


class SyntheticUrlTests(unittest.TestCase):
    def test_url_less_stories_from_one_email_stay_distinct_after_normalizing(self) -> None:
        stories = [{"title": "Essay one"}, {"title": "Essay two"}]
        items = email_fetcher._stories_to_raw_items(stories, "Import AI", "<m1@x>", None)
        urls = {normalize_url(i.url) for i in items}
        self.assertEqual(len(urls), 2)


if __name__ == "__main__":
    unittest.main()
