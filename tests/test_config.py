"""Tests for config load/save: env secrets and code defaults must never be
written back to config.yaml by the dashboard's save path."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from ainews.config import load_config, save_config

_SECRET_ENV = ("ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "AINEWS_EMAIL_PASSWORD")


def _env(**values: str) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _SECRET_ENV}
    env.update(values)
    return env


class SaveConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp())
        self.path = self.dir / "config.yaml"

    def _write(self, data: dict) -> None:
        self.path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    def _raw(self) -> dict:
        return yaml.safe_load(self.path.read_text(encoding="utf-8"))

    def test_env_api_keys_and_password_are_never_written_to_disk(self) -> None:
        self._write({
            "anthropic_api_key": "YOUR_API_KEY_HERE",
            "newsletters": {"enabled": True, "email": "me@x.com"},
            "feeds": [],
        })
        env = _env(ANTHROPIC_API_KEY="sk-env-secret",
                   ELEVENLABS_API_KEY="el-env-secret",
                   AINEWS_EMAIL_PASSWORD="pw-env-secret")
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = load_config(self.path)
            self.assertEqual(cfg["anthropic_api_key"], "sk-env-secret")
            cfg["dedup_threshold"] = 70
            save_config(cfg, self.path)

        text = self.path.read_text(encoding="utf-8")
        for secret in ("sk-env-secret", "el-env-secret", "pw-env-secret"):
            self.assertNotIn(secret, text)
        raw = self._raw()
        self.assertEqual(raw["anthropic_api_key"], "YOUR_API_KEY_HERE")
        self.assertEqual(raw["dedup_threshold"], 70)

    def test_code_defaults_are_not_frozen_into_the_file(self) -> None:
        self._write({"model": "claude-x", "feeds": []})
        with mock.patch.dict(os.environ, _env(), clear=True):
            cfg = load_config(self.path)
            cfg["max_search_results"] = 9
            save_config(cfg, self.path)
        self.assertEqual(self._raw(), {"model": "claude-x", "feeds": [], "max_search_results": 9})

    def test_nested_change_saves_only_the_changed_key(self) -> None:
        self._write({"newsletters": {"enabled": True}, "feeds": []})
        with mock.patch.dict(os.environ, _env(), clear=True):
            cfg = load_config(self.path)
            cfg["newsletters"]["imap_host"] = "imap.example.com"
            save_config(cfg, self.path)
        self.assertEqual(self._raw()["newsletters"],
                         {"enabled": True, "imap_host": "imap.example.com"})

    def test_removed_key_is_removed_from_the_file(self) -> None:
        self._write({"scoring_prompt": "custom", "feeds": []})
        with mock.patch.dict(os.environ, _env(), clear=True):
            cfg = load_config(self.path)
            cfg.pop("scoring_prompt")
            save_config(cfg, self.path)
        self.assertNotIn("scoring_prompt", self._raw())

    def test_list_edits_are_saved(self) -> None:
        feeds = [{"name": "A", "url": "https://a", "category": "trusted"},
                 {"name": "B", "url": "https://b", "category": "open"}]
        self._write({"feeds": feeds})
        with mock.patch.dict(os.environ, _env(), clear=True):
            cfg = load_config(self.path)
            cfg["feeds"].pop(0)
            save_config(cfg, self.path)
        self.assertEqual([f["name"] for f in self._raw()["feeds"]], ["B"])

    def test_save_leaves_no_temp_files_behind(self) -> None:
        self._write({"feeds": []})
        with mock.patch.dict(os.environ, _env(), clear=True):
            cfg = load_config(self.path)
            cfg["dedup_threshold"] = 75
            save_config(cfg, self.path)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["config.yaml"])

    @unittest.skipIf(os.name == "nt", "POSIX permissions")
    def test_saved_file_is_owner_only(self) -> None:
        self._write({"feeds": []})
        with mock.patch.dict(os.environ, _env(), clear=True):
            cfg = load_config(self.path)
            cfg["dedup_threshold"] = 75
            save_config(cfg, self.path)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)


class LoadConfigTests(unittest.TestCase):
    def test_empty_file_loads_with_defaults(self) -> None:
        path = Path(tempfile.mkdtemp()) / "config.yaml"
        path.write_text("", encoding="utf-8")
        with mock.patch.dict(os.environ, _env(), clear=True):
            cfg = load_config(path)
        self.assertEqual(cfg["feeds"], [])


if __name__ == "__main__":
    unittest.main()
