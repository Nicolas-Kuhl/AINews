"""Decide whether the dashboard may serve a request, before any UI renders.

The dashboard fails closed: without an auth config it refuses to serve
unless the operator explicitly opts out (for a localhost-only setup or one
already behind nginx basic auth). It also refuses the example config's
published cookie key and password hash — anyone who knows that key can
forge a session cookie, and the hash is for "changeme123".
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml

AUTH_DISABLED_ENV = "AINEWS_AUTH_DISABLED"

# Values shipped in auth_config.example.yaml.
EXAMPLE_COOKIE_KEY = "change_this_to_a_random_string_32_characters_long"
EXAMPLE_PASSWORD_HASH = "$2b$12$WiP3aa8evuV22jHKwfmz/u70/RNvqmSDz0dDl2oSSxsV2lD9QayXW"

_MIN_COOKIE_KEY_LEN = 16


def auth_decision(auth_config_path: Path) -> tuple[str, Optional[str]]:
    """Return ("login", None), ("disabled", None) or ("refuse", reason)."""
    if not Path(auth_config_path).exists():
        if os.environ.get(AUTH_DISABLED_ENV) == "1":
            return "disabled", None
        return "refuse", (
            "No auth_config.yaml found, so the dashboard is locked. Run "
            "scripts/setup_auth.sh to create one, or set "
            f"{AUTH_DISABLED_ENV}=1 if access is already restricted another way "
            "(localhost only, or nginx basic auth in front)."
        )

    with open(auth_config_path, encoding="utf-8") as f:
        auth_config = yaml.safe_load(f) or {}

    key = str((auth_config.get("cookie") or {}).get("key") or "")
    if key == EXAMPLE_COOKIE_KEY or len(key) < _MIN_COOKIE_KEY_LEN:
        return "refuse", (
            "auth_config.yaml still uses the example cookie key (or one shorter "
            f"than {_MIN_COOKIE_KEY_LEN} characters), which lets anyone forge a "
            "login cookie. Set cookie.key to the output of: "
            'python -c "import secrets; print(secrets.token_urlsafe(32))"'
        )

    users = ((auth_config.get("credentials") or {}).get("usernames") or {})
    if any((u or {}).get("password") == EXAMPLE_PASSWORD_HASH for u in users.values()):
        return "refuse", (
            "auth_config.yaml still has the example password (changeme123). "
            "Set a new hash with: python scripts/generate_password_hash.py"
        )

    return "login", None
