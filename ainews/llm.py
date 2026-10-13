"""Claude models per task, and the one place requests are built and read.

Every pipeline task names its model and effort here (overridable under
``models:`` / ``effort:`` in config.yaml), so a model upgrade is a one-line
change instead of a hunt through scattered defaults.

Current Claude models think adaptively by default: a response can start
with ``thinking`` blocks before any text, so text is read by block type,
never ``content[0]``. Effort is the control for how much the model thinks
(and so for latency and cost); ``max_tokens`` covers thinking plus reply.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_MODELS = {
    "scoring": "claude-sonnet-5-5",
    "dedup_judge": "claude-sonnet-5-5",
    "newsletter_extraction": "claude-sonnet-5-5",
    "brief": "claude-sonnet-5-5",
    "video_script": "claude-sonnet-5-5",
    "learning_objectives": "claude-opus-5-5",
}

# Starting points: low for classification, extraction and short content
# generation; medium for the long, constraint-heavy episode script and the
# research-and-tool-use learning objectives. Tune per task from config.
DEFAULT_EFFORT = {
    "scoring": "low",
    "dedup_judge": "low",
    "newsletter_extraction": "low",
    "brief": "low",
    "video_script": "medium",
    "learning_objectives": "medium",
}

TASKS = tuple(DEFAULT_MODELS)

# Server-side fallback: if a safety classifier declines a request, the API
# retries it on Anthropic's recommended model for that refusal category
# instead of returning the refusal. Claude API only; not offered for Haiku.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
_FALLBACK_MODEL_PREFIXES = ("claude-opus-5", "claude-sonnet-5-5", "claude-fable-5")


class ClaudeRefusal(RuntimeError):
    """The request was declined (after any server-side fallback)."""

    def __init__(self, category: Optional[str]):
        super().__init__(f"Claude declined the request (category: {category or 'unspecified'})")
        self.category = category


class ClaudeTruncated(RuntimeError):
    """The response hit max_tokens before finishing."""


def model_for(cfg: dict, task: str) -> str:
    return (cfg.get("models") or {}).get(task) or DEFAULT_MODELS[task]


def effort_for(cfg: dict, task: str) -> str:
    return (cfg.get("effort") or {}).get(task) or DEFAULT_EFFORT[task]


def create(
    client,
    *,
    model: str,
    effort: str,
    messages: list,
    max_tokens: int,
    system: Optional[str] = None,
    tools: Optional[list] = None,
) -> Any:
    """Send a Messages request; returns the raw response (for tool loops)."""
    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
        "output_config": {"effort": effort},
    }
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = tools
    if model.startswith(_FALLBACK_MODEL_PREFIXES):
        kwargs["betas"] = [FALLBACK_BETA]
        kwargs["fallbacks"] = "default"
        return client.beta.messages.create(**kwargs)
    return client.messages.create(**kwargs)


def response_text(resp, *, allow_truncated: bool = False) -> str:
    """The response's text, by block type; raises on refusal, and on
    truncation unless the caller can salvage partial output."""
    if resp.stop_reason == "refusal":
        category = getattr(getattr(resp, "stop_details", None), "category", None)
        raise ClaudeRefusal(category)
    if resp.stop_reason == "max_tokens" and not allow_truncated:
        raise ClaudeTruncated("response hit max_tokens; raise it or lower effort")
    return "".join(block.text for block in resp.content if block.type == "text")


def complete(
    client,
    *,
    model: str,
    effort: str,
    prompt: str,
    max_tokens: int,
    system: Optional[str] = None,
) -> str:
    """Single-turn request returning the reply text."""
    resp = create(
        client, model=model, effort=effort, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return response_text(resp)
