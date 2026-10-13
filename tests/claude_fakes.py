"""Test double for anthropic.Anthropic that answers like current Claude models.

Responses start with a ``thinking`` block (empty text, as under the default
``display: "omitted"``) before the text, so code that reads
``response.content[0].text`` fails here exactly as it would in production.
"""

from __future__ import annotations

from types import SimpleNamespace


def text_block(text: str):
    return SimpleNamespace(type="text", text=text)


def thinking_block():
    return SimpleNamespace(type="thinking", thinking="", signature="sig")


def tool_use_block(name: str, tool_input: dict, block_id: str = "toolu_1"):
    return SimpleNamespace(type="tool_use", name=name, input=tool_input, id=block_id)


def message(*blocks, stop_reason: str = "end_turn", category=None):
    details = None
    if stop_reason == "refusal":
        details = SimpleNamespace(type="refusal", category=category, explanation=None)
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason, stop_details=details)


class FakeClaude:
    """Records every request and replies from a queue.

    Each queued reply may be a string (sent as thinking + text), a ready-made
    message, an exception to raise, or a callable taking the request kwargs.
    The last reply is reused once the queue runs down to it.
    """

    def __init__(self, *replies):
        self.requests: list[dict] = []
        self._replies = list(replies)
        messages = SimpleNamespace(create=self._create)
        self.messages = messages
        self.beta = SimpleNamespace(messages=messages)

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        reply = self._replies.pop(0) if len(self._replies) > 1 else self._replies[0]
        if callable(reply) and not isinstance(reply, SimpleNamespace):
            reply = reply(kwargs)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, str):
            reply = message(thinking_block(), text_block(reply))
        return reply
