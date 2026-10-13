"""Tests for the shared Claude request helpers and per-task model config."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from ainews import llm
from ainews.config import load_config
from claude_fakes import FakeClaude, message, text_block, thinking_block


class ResponseTextTests(unittest.TestCase):
    def test_text_is_read_by_block_type_not_position(self) -> None:
        resp = message(thinking_block(), text_block("Hello "), text_block("world"))
        self.assertEqual(llm.response_text(resp), "Hello world")

    def test_refusal_raises_with_its_category(self) -> None:
        with self.assertRaises(llm.ClaudeRefusal) as ctx:
            llm.response_text(message(stop_reason="refusal", category="frontier_llm"))
        self.assertEqual(ctx.exception.category, "frontier_llm")

    def test_truncated_output_raises(self) -> None:
        with self.assertRaises(llm.ClaudeTruncated):
            llm.response_text(message(thinking_block(), stop_reason="max_tokens"))

    def test_truncated_output_can_be_accepted_by_callers_that_salvage_it(self) -> None:
        resp = message(thinking_block(), text_block('[{"a": 1}, {"b"'), stop_reason="max_tokens")
        self.assertEqual(llm.response_text(resp, allow_truncated=True), '[{"a": 1}, {"b"')


class CreateTests(unittest.TestCase):
    def test_request_carries_model_effort_and_refusal_fallback(self) -> None:
        client = FakeClaude("ok")
        text = llm.complete(client, model="claude-sonnet-5-5", effort="low",
                            prompt="Say ok", max_tokens=1000)
        self.assertEqual(text, "ok")
        req = client.requests[0]
        self.assertEqual(req["model"], "claude-sonnet-5-5")
        self.assertEqual(req["output_config"], {"effort": "low"})
        self.assertEqual(req["fallbacks"], "default")
        self.assertEqual(req["betas"], [llm.FALLBACK_BETA])
        self.assertEqual(req["messages"], [{"role": "user", "content": "Say ok"}])
        for removed in ("thinking", "temperature", "top_p", "top_k"):
            self.assertNotIn(removed, req)

    def test_models_without_server_side_fallback_do_not_send_it(self) -> None:
        client = FakeClaude("ok")
        llm.complete(client, model="claude-haiku-5-5", effort="low",
                     prompt="Say ok", max_tokens=1000)
        self.assertNotIn("fallbacks", client.requests[0])
        self.assertNotIn("betas", client.requests[0])


class TaskConfigTests(unittest.TestCase):
    def _load(self, data: dict) -> dict:
        path = Path(tempfile.mkdtemp()) / "config.yaml"
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
        env = {k: v for k, v in os.environ.items()
               if k not in ("ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "AINEWS_EMAIL_PASSWORD")}
        with mock.patch.dict(os.environ, env, clear=True):
            return load_config(path)

    def test_every_task_has_a_model_and_effort_by_default(self) -> None:
        cfg = self._load({"feeds": []})
        for task in llm.TASKS:
            self.assertEqual(llm.model_for(cfg, task), llm.DEFAULT_MODELS[task])
            self.assertEqual(llm.effort_for(cfg, task), llm.DEFAULT_EFFORT[task])

    def test_per_task_overrides_apply(self) -> None:
        cfg = self._load({"models": {"video_script": "claude-opus-5-5"},
                          "effort": {"scoring": "medium"}})
        self.assertEqual(llm.model_for(cfg, "video_script"), "claude-opus-5-5")
        self.assertEqual(llm.effort_for(cfg, "scoring"), "medium")
        self.assertEqual(llm.model_for(cfg, "scoring"), llm.DEFAULT_MODELS["scoring"])

    def test_legacy_model_keys_no_longer_pin_old_models(self) -> None:
        # Frozen into config.yaml by the old save_config; they would keep the
        # pipeline on retired-generation models with the new request shape.
        cfg = self._load({"model": "claude-sonnet-4-5-20250929", "lo_model": "claude-opus-4-6",
                          "video_script": {"model": "claude-sonnet-4-6"},
                          "newsletters": {"model": "claude-sonnet-4-5-20250929"}})
        self.assertEqual(llm.model_for(cfg, "scoring"), "claude-sonnet-5-5")
        self.assertEqual(llm.model_for(cfg, "learning_objectives"), "claude-opus-5-5")
        self.assertEqual(llm.model_for(cfg, "video_script"), "claude-sonnet-5-5")
        self.assertEqual(llm.model_for(cfg, "newsletter_extraction"), "claude-sonnet-5-5")

    def test_ignored_legacy_model_keys_are_logged(self) -> None:
        with self.assertLogs("ainews.config", level="WARNING") as logs:
            self._load({"model": "claude-sonnet-4-5-20250929", "lo_model": "claude-opus-4-6"})
        self.assertIn("model", logs.output[0])
        self.assertIn("lo_model", logs.output[0])

    def test_no_legacy_model_key_is_added_by_default(self) -> None:
        self.assertNotIn("model", self._load({"feeds": []}))


if __name__ == "__main__":
    unittest.main()
