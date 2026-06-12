"""Tests for the email newsletter (compose, render, send)."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ainews.models import ProcessedNewsItem
from ainews.newsletter.compose import compose_newsletter
from ainews.newsletter.render import render_html, render_text
from ainews.newsletter.send import send_newsletter
from ainews.storage.database import Database


def _item(title, score=7, hours_ago=2, source="OpenAI News", url=None):
    return ProcessedNewsItem(
        title=title, url=url or f"https://example.com/{abs(hash(title))}",
        source=source, published=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
        summary=f"Summary of {title}.", short_summary=f"Dek for {title}.",
        score=score, score_reasoning="", category="New Releases",
        fetched_via="rss", processed_at=datetime.now(timezone.utc),
    )


class _StubMsgs:
    def __init__(self, text):
        self._text = text
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)

        class B:
            def __init__(s, t): s.text = t

        class R:
            def __init__(s, t): s.content = [B(t)]
        return R(self._text)


class _StubClient:
    def __init__(self, text="A punchy **intro** paragraph."):
        self.messages = _StubMsgs(text)


class ComposeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db = Database(str(self.tmp / "t.db"))
        self.nldir = self.tmp / "newsletters"
        self.scripts = self.tmp / "scripts"

    def tearDown(self):
        self.db.close()

    def test_composes_more_stories_than_video(self):
        for i in range(15):
            self.db.insert(_item(f"Story {i}", score=7))
        nl = compose_newsletter(
            self.db, _StubClient(), newsletter_dir=self.nldir,
            scripts_dir=self.scripts, max_stories=12,
        )
        self.assertEqual(len(nl["stories"]), 12)
        self.assertIn("intro", nl)
        self.assertEqual(nl["meta"]["story_count"], 12)

    def test_excludes_previously_sent(self):
        import json
        a = _item("Already sent story", score=9)
        self.db.insert(a)
        self.db.insert(_item("Fresh story", score=8))
        self.nldir.mkdir(parents=True)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        (self.nldir / f"{today}.json").write_text(
            json.dumps({"meta": {"story_urls": [a.url]}}))

        nl = compose_newsletter(
            self.db, _StubClient(), newsletter_dir=self.nldir,
            scripts_dir=self.scripts, max_stories=12,
        )
        titles = [s["headline"] for s in nl["stories"]]
        self.assertIn("Fresh story", titles)
        self.assertNotIn("Already sent story", titles)

    def test_subject_uses_video_title_when_present(self):
        import json
        self.db.insert(_item("Big news", score=9))
        self.scripts.mkdir(parents=True)
        d = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        (self.scripts / f"{d}.json").write_text(json.dumps({"title": "Robots Win Again"}))

        nl = compose_newsletter(
            self.db, _StubClient(), newsletter_dir=self.nldir, scripts_dir=self.scripts)
        self.assertIn("Robots Win Again", nl["subject"])

    def test_none_when_no_stories(self):
        nl = compose_newsletter(
            self.db, _StubClient(), newsletter_dir=self.nldir, scripts_dir=self.scripts)
        self.assertIsNone(nl)


class RenderTests(unittest.TestCase):
    def _nl(self):
        return {
            "issue_date": "2026-06-11",
            "subject": "The Daily Prompt — Test",
            "intro": "Line one.\nLine two.",
            "video_url": "https://ainews.eyrean.com/videos/2026-06-11.mp4",
            "site_url": "https://ainews.eyrean.com",
            "stories": [
                {"headline": "Headline <one> & more", "url": "https://x.com/a",
                 "source": "Wired", "summary": "A <b>summary</b>.", "category": "Research",
                 "score": 9, "sources": ["Wired", "TechCrunch", "Verge"],
                 "is_vendor_announcement": True, "source_count": 3},
            ],
        }

    def test_html_escapes_and_includes_pieces(self):
        html = render_html(self._nl())
        self.assertIn("Headline &lt;one&gt; &amp; more", html)   # escaped
        self.assertIn("A &lt;b&gt;summary&lt;/b&gt;.", html)
        self.assertIn("Watch today's 5-minute episode", html)
        self.assertIn("https://x.com/a", html)
        self.assertIn("announcement", html)
        self.assertIn("3 outlets", html)

    def test_text_fallback(self):
        text = render_text(self._nl())
        self.assertIn("01. Headline <one> & more (Wired)", text)
        self.assertIn("https://x.com/a", text)
        self.assertIn("unsubscribe", text.lower())


class SendTests(unittest.TestCase):
    class _FakeSES:
        def __init__(self, fail=()):
            self.fail = set(fail)
            self.sent = []

        def send_raw_email(self, Source, Destinations, RawMessage):
            to = Destinations[0]
            if to in self.fail:
                raise RuntimeError("MessageRejected")
            self.sent.append((to, RawMessage["Data"]))
            return {"MessageId": "abc"}

    def test_sends_to_each_with_unsubscribe_header(self):
        ses = self._FakeSES()
        res = send_newsletter(
            subject="S", html="<p>h</p>", text="t",
            from_addr="news@eyrean.com", recipients=["a@x.com", "b@x.com"],
            unsubscribe="news@eyrean.com", ses_client=ses,
        )
        self.assertEqual(set(res["sent"]), {"a@x.com", "b@x.com"})
        self.assertEqual(res["failed"], {})
        # header present in the raw message
        self.assertIn("List-Unsubscribe", ses.sent[0][1])

    def test_partial_failure_reported(self):
        ses = self._FakeSES(fail={"b@x.com"})
        res = send_newsletter(
            subject="S", html="h", text="t", from_addr="n@x.com",
            recipients=["a@x.com", "b@x.com"], ses_client=ses,
        )
        self.assertEqual(res["sent"], ["a@x.com"])
        self.assertIn("b@x.com", res["failed"])


if __name__ == "__main__":
    unittest.main()
