"""Tests for article content fetching: SSRF guard, content-type and size caps.

Uses httpx.MockTransport with literal public IPs, so no DNS or network.
"""

from __future__ import annotations

import asyncio
import unittest

import httpx

from ainews.fetchers import content_fetcher
from ainews.models import RawNewsItem

PUBLIC = "http://93.184.215.14"

_ARTICLE = (
    "<html><head><title>Lab ships model</title></head><body><article>"
    "<h1>Lab ships model</h1>"
    + "".join(
        f"<p>Paragraph {i}: the lab released a new model today with notable "
        f"improvements in reasoning, coding and long-context retrieval.</p>"
        for i in range(8)
    )
    + "</article></body></html>"
)


def _item(url: str) -> RawNewsItem:
    return RawNewsItem(title="t", url=url, source="s", fetched_via="rss")


def _run(items, handler, max_length=10000):
    seen: list[str] = []

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return handler(request)

    async def go():
        client = content_fetcher._make_client(5, transport=httpx.MockTransport(recording))
        async with client:
            sem = asyncio.Semaphore(4)
            await asyncio.gather(*(content_fetcher._fetch_one(client, it, max_length, sem)
                                   for it in items))

    asyncio.run(go())
    return seen


class ContentFetcherTests(unittest.TestCase):
    def test_public_article_is_fetched_and_extracted(self) -> None:
        item = _item(f"{PUBLIC}/news/a")
        _run([item], lambda r: httpx.Response(
            200, headers={"content-type": "text/html; charset=utf-8"}, text=_ARTICLE))
        self.assertIn("released a new model", item.content or "")

    def test_private_address_is_never_requested(self) -> None:
        item = _item("http://127.0.0.1:8501/")
        seen = _run([item], lambda r: httpx.Response(200, text=_ARTICLE))
        self.assertEqual(seen, [])
        self.assertIsNone(item.content)

    def test_redirect_to_instance_metadata_is_not_followed(self) -> None:
        item = _item(f"{PUBLIC}/go")

        def handler(request):
            if request.url.host == "93.184.215.14":
                return httpx.Response(302, headers={
                    "location": "http://169.254.169.254/latest/meta-data/"})
            return httpx.Response(200, text="SECRET-CREDENTIALS")

        seen = _run([item], handler)
        self.assertEqual(seen, [f"{PUBLIC}/go"])
        self.assertIsNone(item.content)

    def test_non_html_responses_are_skipped(self) -> None:
        item = _item(f"{PUBLIC}/paper.pdf")
        _run([item], lambda r: httpx.Response(
            200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.7 ..."))
        self.assertIsNone(item.content)

    def test_body_download_stops_at_the_size_cap(self) -> None:
        consumed = {"bytes": 0}
        chunk = b"<p>" + b"x" * 65_533 + b"</p>"  # 64 KiB

        class Endless(httpx.AsyncByteStream):
            async def __aiter__(self):
                for _ in range(1000):  # ~64 MB if fully read
                    consumed["bytes"] += len(chunk)
                    yield chunk

        item = _item(f"{PUBLIC}/huge")
        _run([item], lambda r: httpx.Response(
            200, headers={"content-type": "text/html"}, stream=Endless()))
        self.assertLessEqual(consumed["bytes"], content_fetcher.MAX_BODY_BYTES + len(chunk))


if __name__ == "__main__":
    unittest.main()
