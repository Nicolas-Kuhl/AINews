"""Tests for the outbound-URL guard (SSRF protection)."""

from __future__ import annotations

import unittest

from ainews.net_safety import is_public_url


def _resolver(mapping: dict[str, list[str]]):
    def resolve(host: str) -> list[str]:
        if host not in mapping:
            raise OSError(f"cannot resolve {host}")
        return mapping[host]
    return resolve


class IsPublicUrlTests(unittest.TestCase):
    def test_public_hostname_is_allowed(self) -> None:
        resolve = _resolver({"news.example.com": ["93.184.215.14"]})
        self.assertTrue(is_public_url("https://news.example.com/a", resolve=resolve))

    def test_internal_addresses_are_rejected(self) -> None:
        for url in (
            "http://127.0.0.1/",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.5/admin",
            "http://192.168.1.1/",
            "http://[::1]:8501/",
            "http://0.0.0.0/",
        ):
            with self.subTest(url=url):
                self.assertFalse(is_public_url(url, resolve=_resolver({})))

    def test_hostname_resolving_to_a_private_address_is_rejected(self) -> None:
        resolve = _resolver({"internal.example.com": ["10.1.2.3"]})
        self.assertFalse(is_public_url("https://internal.example.com/", resolve=resolve))

    def test_any_private_address_among_several_is_rejected(self) -> None:
        resolve = _resolver({"mixed.example.com": ["93.184.215.14", "127.0.0.1"]})
        self.assertFalse(is_public_url("https://mixed.example.com/", resolve=resolve))

    def test_unresolvable_host_is_rejected(self) -> None:
        self.assertFalse(is_public_url("https://nope.invalid/", resolve=_resolver({})))

    def test_non_http_schemes_are_rejected(self) -> None:
        for url in ("file:///etc/passwd", "newsletter://x/1", "javascript:alert(1)", "ftp://x/"):
            with self.subTest(url=url):
                self.assertFalse(is_public_url(url, resolve=_resolver({})))


if __name__ == "__main__":
    unittest.main()
