"""Dashboard auth must fail closed and refuse the shipped example secrets."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from ainews.auth_guard import (
    AUTH_DISABLED_ENV,
    EXAMPLE_COOKIE_KEY,
    EXAMPLE_PASSWORD_HASH,
    auth_decision,
)

_REAL_HASH = "$2b$12$abcdefghijklmnopqrstuuYmT4l0Ywq7Hc9G0yY0Q2c1gq3tq8x7Wq"
_REAL_KEY = "kY3v9Zr0aQmP2xL7tN5bW8cE1dF4gH6j"


def _write_auth(path: Path, *, key: str = _REAL_KEY, password: str = _REAL_HASH) -> None:
    path.write_text(yaml.safe_dump({
        "credentials": {"usernames": {"admin": {"name": "A", "password": password}}},
        "cookie": {"name": "c", "key": key, "expiry_days": 30},
    }), encoding="utf-8")


class AuthDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = Path(tempfile.mkdtemp()) / "auth_config.yaml"
        env = {k: v for k, v in os.environ.items() if k != AUTH_DISABLED_ENV}
        self._env = mock.patch.dict(os.environ, env, clear=True)
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()

    def test_missing_config_refuses_access(self) -> None:
        mode, message = auth_decision(self.path)
        self.assertEqual(mode, "refuse")
        self.assertIn("auth_config.yaml", message)

    def test_missing_config_with_explicit_opt_out_disables_login(self) -> None:
        os.environ[AUTH_DISABLED_ENV] = "1"
        self.assertEqual(auth_decision(self.path), ("disabled", None))

    def test_example_cookie_key_is_refused(self) -> None:
        _write_auth(self.path, key=EXAMPLE_COOKIE_KEY)
        mode, message = auth_decision(self.path)
        self.assertEqual(mode, "refuse")
        self.assertIn("cookie", message)

    def test_example_password_hash_is_refused(self) -> None:
        _write_auth(self.path, password=EXAMPLE_PASSWORD_HASH)
        mode, message = auth_decision(self.path)
        self.assertEqual(mode, "refuse")
        self.assertIn("changeme123", message)

    def test_customised_config_requires_login(self) -> None:
        _write_auth(self.path)
        self.assertEqual(auth_decision(self.path), ("login", None))

    def test_opt_out_does_not_override_an_existing_config(self) -> None:
        os.environ[AUTH_DISABLED_ENV] = "1"
        _write_auth(self.path)
        self.assertEqual(auth_decision(self.path), ("login", None))


if __name__ == "__main__":
    unittest.main()
