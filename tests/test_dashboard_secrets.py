"""The Settings page must never send a stored secret back to the browser."""

from __future__ import annotations

import os
import unittest
from unittest import mock

import dashboard_components as dc


class SecretFieldTests(unittest.TestCase):
    def test_stored_password_is_described_not_prefilled(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            placeholder, disabled = dc._secret_field_state("hunter2", "AINEWS_EMAIL_PASSWORD")
        self.assertNotIn("hunter2", placeholder)
        self.assertIn("saved", placeholder)
        self.assertFalse(disabled)

    def test_env_supplied_password_disables_the_field(self) -> None:
        with mock.patch.dict(os.environ, {"AINEWS_EMAIL_PASSWORD": "from-env"}, clear=True):
            placeholder, disabled = dc._secret_field_state("", "AINEWS_EMAIL_PASSWORD")
        self.assertNotIn("from-env", placeholder)
        self.assertIn("AINEWS_EMAIL_PASSWORD", placeholder)
        self.assertTrue(disabled)

    def test_empty_input_keeps_the_stored_password(self) -> None:
        self.assertIsNone(dc._secret_to_save("", "hunter2"))

    def test_typed_password_replaces_the_stored_one(self) -> None:
        self.assertEqual(dc._secret_to_save("new-pass", "hunter2"), "new-pass")

    def test_retyping_the_same_password_is_not_a_change(self) -> None:
        self.assertIsNone(dc._secret_to_save("hunter2", "hunter2"))


class WebSearchTlsTests(unittest.TestCase):
    def test_web_search_keeps_tls_verification_on(self) -> None:
        with mock.patch.object(dc, "DDGS") as ddgs_cls:
            ddgs_cls.return_value.__enter__.return_value.text.return_value = []
            dc._search_web_for_context("query")
        _, kwargs = ddgs_cls.call_args
        self.assertIsNot(kwargs.get("verify", True), False)


if __name__ == "__main__":
    unittest.main()
