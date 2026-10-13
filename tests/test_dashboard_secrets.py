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




class LearningObjectivesTests(unittest.TestCase):
    """Opus tool loop: no budget_tokens (a 400 on current Opus), the task
    model and effort, and an append-only history across tool calls."""

    def _item(self):
        from types import SimpleNamespace
        return SimpleNamespace(title="Lab ships model", source="Lab", summary="s", url="https://x")

    def test_tool_loop_runs_on_the_task_model_without_a_thinking_budget(self) -> None:
        from claude_fakes import FakeClaude, message, text_block, thinking_block, tool_use_block
        from ainews import llm

        client = FakeClaude(
            message(thinking_block(), tool_use_block("web_search", {"query": "lab model"}),
                    stop_reason="tool_use"),
            "- Explain the new model",
        )
        cfg = {"anthropic_api_key": "sk-test", "lo_web_research": True}
        with mock.patch.object(dc.anthropic, "Anthropic", return_value=client), \
             mock.patch.object(dc, "_search_web_for_context", return_value="results"):
            out = dc.generate_learning_objectives(cfg, self._item())

        self.assertEqual(out, "- Explain the new model")
        first, second = client.requests
        self.assertEqual(first["model"], llm.DEFAULT_MODELS["learning_objectives"])
        self.assertEqual(first["output_config"], {"effort": llm.DEFAULT_EFFORT["learning_objectives"]})
        self.assertNotIn("thinking", first)
        # Append-only: the second request repeats the first verbatim, then adds
        # the assistant turn (thinking blocks included) and the tool result.
        self.assertEqual(second["tools"], first["tools"])
        self.assertEqual(second["messages"][0], first["messages"][0])
        self.assertEqual(second["messages"][1]["role"], "assistant")
        self.assertEqual(second["messages"][1]["content"][0].type, "thinking")
        self.assertEqual(second["messages"][2]["content"][0]["type"], "tool_result")

    def test_unknown_tool_gets_an_error_result_instead_of_a_400(self) -> None:
        from claude_fakes import FakeClaude, message, thinking_block, tool_use_block

        client = FakeClaude(
            message(thinking_block(), tool_use_block("browse", {"url": "x"}), stop_reason="tool_use"),
            "- Objective",
        )
        cfg = {"anthropic_api_key": "sk-test", "lo_web_research": True}
        with mock.patch.object(dc.anthropic, "Anthropic", return_value=client), \
             mock.patch.object(dc, "_search_web_for_context", return_value="results"):
            dc.generate_learning_objectives(cfg, self._item())
        result = client.requests[1]["messages"][2]["content"][0]
        self.assertTrue(result["is_error"])


if __name__ == "__main__":
    unittest.main()
