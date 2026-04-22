"""Streamlit custom component that renders the editorial triage console."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

import streamlit.components.v1 as components

_BUILD_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"

_reader = components.declare_component(
    "ainews_reader",
    path=str(_BUILD_DIR),
)


def reader(
    by_day: Iterable[Mapping[str, Any]],
    *,
    theme_default: str = "paper",
    key: str | None = None,
) -> Any:
    """Render the triage console component.

    Parameters
    ----------
    by_day:
        Iterable of ``{"date", "label", "stories"}`` dicts, one per day,
        pre-sorted newest first. Each story is the enriched payload produced
        by :func:`ainews.dashboard.payload.build_day_payload`.
    theme_default:
        Initial theme — ``"paper"`` or ``"terminal"``. The component owns
        subsequent toggling via ``localStorage``.
    key:
        Streamlit component key.
    """

    return _reader(
        by_day=list(by_day),
        theme_default=theme_default,
        default=None,
        key=key,
    )
