#!/usr/bin/env python3
"""AI News Aggregator — Streamlit dashboard."""

import subprocess
import sys
import html
from datetime import datetime, timedelta
from pathlib import Path

import anthropic
import streamlit as st

from ainews.config import load_config, save_config, CONFIG_PATH
from ainews.models import ProcessedNewsItem
from ainews.processing.grouper import run_grouper
from ainews.storage.database import Database

PROJECT_ROOT = Path(__file__).resolve().parent

DEFAULT_LO_PROMPT = """\
You are an expert AI curriculum designer creating learning objectives for \
educational video content about AI developments.

Given the following news item, generate 3-5 concise, actionable learning \
objectives that a course or video covering this topic should teach.

Research and consider:
- What is fundamentally new or important about this development?
- What technical concepts should learners understand?
- What practical skills or knowledge would be most valuable?
- How does this fit into the broader AI landscape?

Each learning objective should:
- Start with an action verb (Explain, Demonstrate, Compare, Implement, Analyze)
- Be specific and measurable
- Focus on the most important takeaways for AI practitioners and enthusiasts
- Be 1-2 sentences max

Title: {title}
Source: {source}
Summary: {summary}
URL: {url}

Respond with ONLY the learning objectives as a markdown bulleted list \
(using - prefix), one per line. No preamble or explanation.\
"""

MINIMALIST_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

    :root {
        --bg-app: #f3f5f2;
        --bg-surface: #ffffff;
        --bg-surface-2: #eef2ee;
        --text-primary: #0f1411;
        --text-muted: #4d5951;
        --text-disabled: #7a877f;
        --accent: #0f766e;
        --accent-hover: #115e59;
        --accent-soft: rgba(15, 118, 110, 0.12);
        --border: #d5ddd7;
        --border-strong: #c4cec7;
        --danger: #be123c;
        --warning: #d97706;
        --radius-sm: 10px;
        --radius-md: 18px;
        --radius-lg: 24px;
        --font-2xs: 0.72rem;
        --font-xs: 0.82rem;
        --font-sm: 0.9rem;
        --font-md: 1.02rem;
        --shadow-soft: 0 22px 46px -34px rgba(10, 24, 16, 0.38);
    }

    .stApp {
        position: relative;
    }

    .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
        color: var(--text-primary);
        font-family: 'Manrope', 'Avenir Next', 'Segoe UI', sans-serif;
        background:
            radial-gradient(920px 460px at 100% -8%, rgba(15, 118, 110, 0.12), transparent 64%),
            radial-gradient(760px 420px at -14% 6%, rgba(71, 85, 74, 0.1), transparent 58%),
            var(--bg-app);
    }

    .block-container {
        padding-top: 1.2rem !important;
        padding-bottom: 1.8rem !important;
        max-width: 1340px !important;
    }

    @keyframes fadeSlideDown {
        from {
            opacity: 0;
            transform: translateY(-8px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }

    @keyframes fadeIn {
        from { opacity: 0; }
        to { opacity: 1; }
    }

    @keyframes pulse {
        0%, 100% { opacity: 0.4; }
        50% { opacity: 1; }
    }

    [data-testid="stSidebar"],
    [data-testid="stSidebar"] > div {
        background:
            linear-gradient(180deg, rgba(255, 255, 255, 0.93), rgba(255, 255, 255, 0.88)),
            radial-gradient(600px 300px at 100% 0%, rgba(15, 118, 110, 0.09), transparent 68%);
        border-right: 1px solid var(--border);
    }

    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] .stMarkdown,
    [data-testid="stSidebar"] span {
        color: var(--text-primary);
    }

    [data-testid="stSidebar"] [data-testid="stWidgetLabel"] label {
        color: var(--text-muted) !important;
        font-size: var(--font-xs) !important;
        font-weight: 600 !important;
        letter-spacing: 0.02em !important;
    }

    .app-hero {
        background:
            linear-gradient(140deg, rgba(255, 255, 255, 0.94), rgba(250, 252, 249, 0.96)),
            radial-gradient(560px 250px at 100% -6%, rgba(15, 118, 110, 0.12), transparent 72%);
        border: 1px solid var(--border);
        border-radius: var(--radius-lg);
        box-shadow: var(--shadow-soft);
        padding: 1.3rem 1.45rem 1.2rem 1.45rem;
        margin: 0.15rem 0 1rem 0;
        animation: fadeSlideDown 0.32s ease-out;
    }

    .hero-eyebrow {
        margin: 0 !important;
        color: var(--accent) !important;
        font-family: 'IBM Plex Mono', 'SF Mono', monospace !important;
        font-size: 0.69rem !important;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        font-weight: 600;
    }

    .app-hero h1 {
        margin: 0.18rem 0 0.14rem 0 !important;
        font-size: 1.9rem !important;
        letter-spacing: -0.03em !important;
        font-weight: 800 !important;
    }

    .hero-sub {
        margin: 0 !important;
        color: var(--text-muted) !important;
        font-size: var(--font-sm) !important;
        max-width: 74ch;
        line-height: 1.65;
    }

    .status-strip {
        margin-top: 0.9rem;
        display: flex;
        flex-wrap: wrap;
        gap: 0.5rem;
    }

    .status-chip {
        display: inline-flex;
        align-items: center;
        background-color: var(--bg-surface-2);
        color: var(--text-muted);
        border: 1px solid var(--border);
        border-radius: 999px;
        padding: 0.26rem 0.74rem;
        font-size: var(--font-2xs);
        font-weight: 600;
        line-height: 1.4;
        animation: fadeIn 0.3s ease-out;
    }

    .status-chip strong {
        color: var(--text-primary);
        margin-left: 0.2rem;
    }

    .status-chip-strong {
        background-color: rgba(15, 118, 110, 0.08);
        border-color: rgba(15, 118, 110, 0.25);
        color: #0b615c;
    }

    h1 {
        color: var(--text-primary) !important;
        font-weight: 800;
        letter-spacing: -0.02em;
        margin-bottom: 0.2rem !important;
    }

    h2, h3 {
        color: var(--text-primary) !important;
        font-weight: 700;
        letter-spacing: -0.01em;
    }

    a {
        color: var(--accent) !important;
        text-decoration: none;
        font-weight: 600;
        transition: color 0.16s ease;
    }

    a:hover { color: var(--accent-hover) !important; }

    [data-testid="stTabs"] [data-baseweb="tab-list"] {
        gap: 0.4rem;
    }

    [data-testid="stTabs"] button[role="tab"] {
        border: 1px solid var(--border) !important;
        border-radius: 999px !important;
        background-color: rgba(255, 255, 255, 0.62) !important;
        color: var(--text-muted) !important;
        font-weight: 500;
        padding: 0.28rem 0.95rem !important;
        transition: color 0.15s ease, border-color 0.15s ease, background-color 0.15s ease;
    }

    [data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
        color: var(--text-primary) !important;
        background-color: rgba(255, 255, 255, 0.95) !important;
        border: 1px solid var(--border-strong) !important;
        box-shadow: inset 0 0 0 1px rgba(15, 118, 110, 0.12);
    }

    [data-testid="stTabs"] button[role="tab"]:hover {
        color: var(--text-primary) !important;
        border-color: var(--border-strong) !important;
    }

    hr { border-color: var(--border) !important; margin: 0.75rem 0 !important; }

    input[type="text"],
    textarea,
    [data-baseweb="input"] > div,
    [data-baseweb="textarea"] > div,
    [data-baseweb="select"] > div {
        background-color: #ffffff !important;
        color: var(--text-primary) !important;
        border: 1px solid var(--border) !important;
        border-radius: var(--radius-sm) !important;
        box-shadow: none !important;
        transition: border-color 0.15s ease, box-shadow 0.15s ease !important;
    }

    input[type="text"]:focus,
    textarea:focus {
        border-color: var(--accent) !important;
        box-shadow: 0 0 0 3px var(--accent-soft) !important;
    }

    .stButton > button {
        background-color: rgba(255, 255, 255, 0.72) !important;
        color: #26332b !important;
        border: 1px solid var(--border) !important;
        border-radius: var(--radius-sm) !important;
        font-weight: 600;
        font-size: var(--font-sm) !important;
        min-height: 2.15rem !important;
        padding: 0.36rem 0.86rem !important;
        box-shadow: none !important;
        transition: color 0.15s ease, background-color 0.15s ease, border-color 0.15s ease, transform 0.1s ease;
    }

    .stButton > button:hover {
        color: var(--text-primary) !important;
        border-color: var(--border-strong) !important;
        background-color: #ffffff !important;
        transform: translateY(-1px);
    }

    .stButton > button:focus,
    .stButton > button:focus-visible {
        box-shadow: none !important;
        outline: 2px solid var(--accent-soft) !important;
        outline-offset: 1px;
    }

    .stButton > button[kind="primary"],
    .stButton > button[kind="primary"]:focus {
        background-color: var(--accent) !important;
        color: #f8fffe !important;
        border: 1px solid var(--accent) !important;
        border-radius: var(--radius-sm) !important;
        min-height: 2.15rem !important;
        padding: 0.36rem 0.9rem !important;
        font-size: var(--font-sm) !important;
        transition: background-color 0.15s ease, transform 0.1s ease;
    }

    .stButton > button[kind="primary"]:hover {
        background-color: var(--accent-hover) !important;
        color: #f8fffe !important;
        transform: translateY(-1px) !important;
    }

    .stButton > button[kind="primary"]:active {
        transform: translateY(0);
    }

    .ack-done-badge {
        display: inline-block;
        background-color: #e9f7f1;
        color: #18794e;
        border: 1px solid #b8e0cf;
        padding: 0.13rem 0.58rem;
        border-radius: 999px;
        font-size: var(--font-2xs);
        font-weight: 700;
        line-height: 1.3;
    }

    [data-baseweb="radio"] label {
        color: var(--text-muted) !important;
    }

    [data-testid="stToggle"] label span[data-testid="stToggleLabel"] {
        color: var(--text-muted) !important;
    }

    [data-testid="stAlert"] {
        background-color: rgba(255, 255, 255, 0.88) !important;
        color: var(--text-muted) !important;
        border: 1px solid var(--border) !important;
        border-radius: var(--radius-md) !important;
        box-shadow: var(--shadow-soft);
    }

    .run-status {
        color: var(--text-muted) !important;
        font-size: var(--font-sm) !important;
        padding: 0.12rem 0 0.35rem 0;
    }

    .run-status strong { color: var(--text-primary); }

    .news-table {
        background: rgba(255, 255, 255, 0.82);
        border: 1px solid var(--border);
        border-radius: var(--radius-md);
        margin-top: 0.36rem;
        box-shadow: var(--shadow-soft);
        overflow: hidden;
        backdrop-filter: blur(8px);
    }

    .table-header {
        background: linear-gradient(180deg, rgba(244, 247, 244, 0.92), rgba(238, 243, 238, 0.95));
        border-bottom: 1px solid var(--border);
        padding: 0.6rem 0.45rem;
        margin-bottom: 0;
    }

    .table-header p, .table-header span {
        color: var(--text-muted) !important;
        font-weight: 600 !important;
        font-size: var(--font-2xs) !important;
        text-transform: uppercase;
        letter-spacing: 0.11em;
    }

    .news-row {
        border-bottom: 1px solid rgba(213, 221, 215, 0.9);
        padding: 0.22rem 0.45rem;
        transition: background-color 0.16s ease, transform 0.16s ease;
        margin: 0;
    }

    .news-row:hover {
        background-color: rgba(248, 251, 248, 0.95);
    }

    .news-row p, .news-row span, .news-row div {
        font-size: var(--font-sm) !important;
        color: var(--text-primary) !important;
        margin-bottom: 0 !important;
        padding-bottom: 0 !important;
    }
    .news-row a { font-size: var(--font-sm) !important; }
    .table-muted {
        color: var(--text-muted) !important;
        font-size: var(--font-sm) !important;
    }

    .news-row .stButton > button {
        font-size: var(--font-2xs) !important;
        padding: 0.12rem 0.48rem !important;
        min-height: 0 !important;
        line-height: 1 !important;
        color: var(--text-muted) !important;
        border-radius: 8px !important;
        transition: color 0.15s ease, background-color 0.15s ease, border-color 0.15s ease;
    }

    .news-row .stButton > button:hover {
        color: var(--accent) !important;
        border-color: rgba(15, 118, 110, 0.28) !important;
        background-color: rgba(15, 118, 110, 0.08) !important;
    }

    .news-table [data-testid="stHorizontalBlock"] {
        gap: 0.4rem !important;
        align-items: center !important;
    }

    .news-table [data-testid="stVerticalBlock"] > div {
        padding-top: 0 !important;
        padding-bottom: 0 !important;
    }

    .news-row [data-testid="stHorizontalBlock"] {
        padding: 0.05rem 0 !important;
        min-height: 1.6rem !important;
    }

    .score-badge {
        display: inline-block;
        font-weight: 700;
        font-size: var(--font-xs);
        color: var(--text-primary);
        border-radius: 999px;
        padding: 0.12rem 0.56rem;
        text-align: center;
        min-width: 2rem;
        line-height: 1.35;
        border: 1px solid transparent;
    }

    .score-badge.score-high {
        background-color: #ffe6ed;
        border-color: #f8b7c7;
        color: #9f1239;
    }

    .score-badge.score-mid {
        background-color: #fff5df;
        border-color: #f6deb0;
        color: #92400e;
    }

    .score-badge.score-low {
        background-color: #edf2ed;
        border-color: #dbe5dd;
        color: #5a665e;
    }

    .detail-panel {
        background: linear-gradient(180deg, rgba(252, 253, 252, 0.98), rgba(247, 250, 247, 0.97));
        border: 1px solid var(--border);
        border-left: 3px solid rgba(15, 118, 110, 0.72);
        border-radius: 0 var(--radius-md) var(--radius-md) 0;
        padding: 1rem 1.2rem;
        margin: 0.2rem 0.5rem 0.5rem 1.8rem;
        animation: fadeSlideDown 0.22s ease-out;
    }

    .detail-panel p {
        color: var(--text-muted) !important;
        font-size: var(--font-xs) !important;
        line-height: 1.6 !important;
    }

    .detail-panel strong { color: var(--text-primary) !important; }

    .detail-label {
        display: inline-block;
        color: var(--text-muted);
        font-size: var(--font-2xs);
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        margin-bottom: 0.2rem;
    }

    .related-link {
        color: var(--text-muted) !important;
        font-size: var(--font-xs) !important;
        padding: 0.2rem 0;
        border-bottom: 1px solid rgba(210, 220, 212, 0.7);
        margin-bottom: 0;
    }

    .related-link:last-child { border-bottom: none; }

    .related-link a { color: var(--accent) !important; font-size: var(--font-xs) !important; }

    .related-count {
        background-color: #e9f5f4;
        color: #0f766e;
        border: 1px solid #c2e6e2;
        border-radius: 999px;
        padding: 0.04rem 0.42rem;
        font-size: var(--font-2xs);
        font-weight: 600;
        margin-left: 0.3rem;
        vertical-align: middle;
    }

    .meta-pill {
        display: inline-block;
        background-color: var(--bg-surface-2);
        color: var(--text-muted);
        border: 1px solid var(--border);
        border-radius: 999px;
        padding: 0.1rem 0.55rem;
        font-size: var(--font-2xs);
        font-weight: 500;
        margin-right: 0.4rem;
        margin-top: 0.4rem;
    }

    .meta-pill strong { color: var(--text-primary) !important; font-size: var(--font-2xs) !important; }

    .settings-card {
        background:
            linear-gradient(180deg, rgba(255, 255, 255, 0.91), rgba(250, 252, 250, 0.92));
        border: 1px solid var(--border);
        border-radius: var(--radius-md);
        padding: 1.02rem 1.12rem;
        margin-bottom: 1rem;
        box-shadow: var(--shadow-soft);
    }

    .settings-help {
        color: var(--text-muted) !important;
        font-size: var(--font-xs) !important;
        line-height: 1.45 !important;
        margin: 0.1rem 0 0.75rem 0 !important;
    }
    .settings-feed-row {
        border-bottom: 1px solid rgba(213, 221, 215, 0.7);
        padding: 0.33rem 0.12rem;
    }

    .settings-feed-row:last-child { border-bottom: none; }

    .feed-name {
        color: var(--text-primary);
        font-weight: 600;
    }

    .feed-url {
        color: var(--text-muted);
        font-size: var(--font-xs);
    }

    .feed-disabled {
        color: var(--text-disabled) !important;
    }

    .query-text {
        color: var(--text-primary);
        font-size: var(--font-sm);
        font-weight: 500;
    }

    .empty-inline-note {
        color: var(--text-disabled);
        font-size: var(--font-xs);
        font-style: italic;
    }

    .about-section {
        color: var(--text-muted) !important;
        line-height: 1.7;
    }

    .about-section h3 {
        color: var(--text-primary) !important;
        margin-top: 1.5rem !important;
    }

    .about-section strong { color: var(--text-primary) !important; }

    .about-section code {
        background-color: #edf4ef !important;
        color: #155e56 !important;
        padding: 0.08rem 0.42rem;
        border-radius: 6px;
        border: 1px solid #d4e2d6;
        font-size: var(--font-sm);
        font-family: 'IBM Plex Mono', 'SF Mono', monospace;
    }

    .empty-state {
        text-align: center;
        padding: 2.5rem 1rem;
        color: var(--text-muted);
    }

    .empty-state .icon {
        font-size: 2.15rem;
        margin-bottom: 0.4rem;
        opacity: 0.38;
    }

    .lo-stale {
        opacity: 0.35;
        transition: opacity 0.3s ease;
    }

    .lo-generating-indicator {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        color: var(--accent);
        font-size: var(--font-xs);
        font-weight: 600;
        padding: 0.6rem 0;
        animation: pulse 1.5s ease-in-out infinite;
    }

    .lo-generating-indicator .dot-loader {
        display: inline-flex;
        gap: 3px;
    }

    .lo-generating-indicator .dot-loader span {
        width: 5px;
        height: 5px;
        border-radius: 50%;
        background-color: var(--accent);
        animation: pulse 1.5s ease-in-out infinite;
    }
    .lo-generating-indicator .dot-loader span:nth-child(2) { animation-delay: 0.2s; }
    .lo-generating-indicator .dot-loader span:nth-child(3) { animation-delay: 0.4s; }

    .lo-opus-badge {
        display: inline-block;
        background-color: #edf5f1;
        color: #185f51;
        border: 1px solid #d4e4da;
        font-size: 0.62rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        padding: 0.18rem 0.52rem;
        border-radius: 999px;
        margin-top: 0.15rem;
    }

    [data-testid="stHorizontalBlock"]:has(.lo-btn-marker) .stButton {
        display: inline-block !important;
        width: auto !important;
    }

    [data-testid="stHorizontalBlock"]:has(.lo-btn-marker) .stButton > button {
        background-color: #edf6f4 !important;
        color: #16665a !important;
        border: 1px solid #cae4de !important;
        border-radius: 999px !important;
        font-family: 'IBM Plex Mono', 'SF Mono', monospace !important;
        font-size: 0.62rem !important;
        font-weight: 600 !important;
        text-transform: uppercase !important;
        letter-spacing: 0.08em !important;
        padding: 0.18rem 0.52rem !important;
        min-height: 0 !important;
        height: auto !important;
        line-height: 1.2 !important;
        margin: 0 !important;
        transition: background-color 0.15s ease, color 0.15s ease;
    }

    [data-testid="stHorizontalBlock"]:has(.lo-btn-marker) .stButton > button:hover {
        background-color: #ddf0ea !important;
        color: #114c45 !important;
    }

    [data-testid="stDateInput"] input,
    [data-testid="stNumberInput"] input {
        background-color: #ffffff !important;
    }

    [data-testid="stStatusWidget"] {
        border: 1px solid var(--border) !important;
        border-radius: var(--radius-md) !important;
        background-color: rgba(255, 255, 255, 0.88) !important;
    }

    [data-testid="stCodeBlock"] pre {
        border-radius: var(--radius-sm) !important;
    }

    @media (max-width: 960px) {
        .block-container {
            padding-top: 0.9rem !important;
        }
        .app-hero {
            border-radius: var(--radius-md);
            padding: 1rem 1rem 0.95rem 1rem;
        }
        .app-hero h1 {
            font-size: 1.55rem !important;
        }
        .hero-sub {
            font-size: 0.84rem !important;
        }
        .detail-panel {
            margin-left: 1rem;
            margin-right: 0.35rem;
        }
        .settings-card {
            padding: 0.92rem 0.9rem;
        }
    }
</style>
"""


def score_class(score: int) -> str:
    if score >= 8:
        return "score-high"
    if score >= 5:
        return "score-mid"
    return "score-low"


def generate_learning_objectives(cfg: dict, item: ProcessedNewsItem) -> str:
    """Call Claude Opus to generate learning objectives for a news item."""
    api_key = cfg.get("anthropic_api_key", "")
    prompt_template = cfg.get("lo_prompt") or DEFAULT_LO_PROMPT
    prompt = prompt_template.format(
        title=item.title,
        source=item.source,
        summary=item.summary or "(no summary available)",
        url=item.url,
    )
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def _render_table(grouped_items, db, cfg):
    """Render grouped news items as a compact table with inline expand arrows."""
    st.markdown('<div class="news-table">', unsafe_allow_html=True)

    # Header
    st.markdown('<div class="table-header">', unsafe_allow_html=True)
    h_exp, h_score, h_title, h_source, h_date, h_ack = st.columns([0.3, 0.5, 6, 2, 1.5, 0.7])
    h_exp.markdown("")
    h_score.markdown("**Score**")
    h_title.markdown("**Title**")
    h_source.markdown("**Source**")
    h_date.markdown("**Date**")
    h_ack.markdown("")
    st.markdown('</div>', unsafe_allow_html=True)

    for primary, related in grouped_items:
        row_key = f"row_{primary.id}"
        is_expanded = st.session_state.get(row_key, False)

        # Row
        st.markdown('<div class="news-row">', unsafe_allow_html=True)
        c_exp, c_score, c_title, c_source, c_date, c_ack = st.columns([0.3, 0.5, 6, 2, 1.5, 0.7])

        with c_exp:
            arrow = "▾" if is_expanded else "▸"
            if st.button(arrow, key=f"toggle_{primary.id}"):
                st.session_state[row_key] = not is_expanded
                st.rerun()

        score_cls = score_class(primary.score)
        c_score.markdown(
            f'<span class="score-badge {score_cls}">{primary.score}</span>',
            unsafe_allow_html=True,
        )

        # Title with related count badge
        title_html = f"[{primary.title}]({primary.url})"
        if related:
            title_html += f' <span class="related-count">+{len(related)}</span>'
        c_title.markdown(title_html, unsafe_allow_html=True)

        c_source.markdown(f'<span class="table-muted">{primary.source}</span>', unsafe_allow_html=True)
        date_label = primary.published.strftime("%b %d") if primary.published else "&mdash;"
        c_date.markdown(
            f'<span class="table-muted">{date_label}</span>',
            unsafe_allow_html=True,
        )
        with c_ack:
            if primary.id is not None:
                if primary.acknowledged:
                    st.markdown(
                        '<span class="ack-done-badge">Ack</span>',
                        unsafe_allow_html=True,
                    )
                else:
                    if st.button("Ack", key=f"ack_{primary.id}", type="primary"):
                        db.acknowledge(primary.id)
                        for rel in related:
                            if rel.id is not None:
                                db.acknowledge(rel.id)
                        st.rerun()

        st.markdown('</div>', unsafe_allow_html=True)

        # Expandable detail panel (animated via CSS)
        if is_expanded:
            st.markdown('<div class="detail-panel">', unsafe_allow_html=True)

            if primary.summary:
                st.markdown(
                    f'<span class="detail-label">Summary</span>\n\n{primary.summary}',
                    unsafe_allow_html=True,
                )

            if primary.score_reasoning:
                st.markdown(
                    f'<span class="detail-label">Score Reasoning</span>\n\n{primary.score_reasoning}',
                    unsafe_allow_html=True,
                )

            # --- Learning Objectives with Generate button ---
            lo_gen_key = f"gen_lo_{primary.id}"
            lo_err_key = f"gen_lo_err_{primary.id}"
            is_generating = st.session_state.get(lo_gen_key, False)

            st.markdown(
                '<span class="detail-label">Learning Objectives</span>',
                unsafe_allow_html=True,
            )
            if not is_generating and not primary.lo_generated_with_opus:
                lo_c1, _ = st.columns([10, 0.1])
                with lo_c1:
                    st.markdown('<span class="lo-btn-marker"></span>', unsafe_allow_html=True)
                    if st.button("Generate With Opus", key=f"gen_lo_btn_{primary.id}"):
                        st.session_state[lo_gen_key] = True
                        st.session_state.pop(lo_err_key, None)
                        st.rerun()
            elif primary.lo_generated_with_opus and not is_generating:
                st.markdown(
                    '<span class="lo-opus-badge">Generated with Opus</span>',
                    unsafe_allow_html=True,
                )

            # Show any previous error
            prev_err = st.session_state.get(lo_err_key)
            if prev_err:
                st.error(prev_err)

            if is_generating:
                # Show old objectives greyed out
                if primary.learning_objectives:
                    st.markdown(
                        f'<div class="lo-stale">{primary.learning_objectives}</div>',
                        unsafe_allow_html=True,
                    )
                # Animated loading indicator
                st.markdown(
                    '<div class="lo-generating-indicator">'
                    '<div class="dot-loader"><span></span><span></span><span></span></div>'
                    ' Generating with Opus...'
                    '</div>',
                    unsafe_allow_html=True,
                )
                try:
                    new_lo = generate_learning_objectives(cfg, primary)
                    db.update_learning_objectives(primary.id, new_lo, generated_with_opus=True)
                    primary.learning_objectives = new_lo
                    primary.lo_generated_with_opus = True
                except Exception as e:
                    st.session_state[lo_err_key] = f"Generation failed: {e}"
                st.session_state[lo_gen_key] = False
                st.rerun()
            else:
                if primary.learning_objectives:
                    st.markdown(primary.learning_objectives, unsafe_allow_html=True)
                else:
                    st.markdown(
                        '<span class="empty-inline-note">'
                        'No learning objectives yet — click Generate With Opus to create them.'
                        '</span>',
                        unsafe_allow_html=True,
                    )

            # Metadata pills
            pills = f'<span class="meta-pill"><strong>{primary.category}</strong></span>'
            pills += f'<span class="meta-pill">via <strong>{primary.fetched_via}</strong></span>'
            if primary.published:
                pills += f'<span class="meta-pill">{primary.published.strftime("%Y-%m-%d")}</span>'
            st.markdown(pills, unsafe_allow_html=True)

            if related:
                st.markdown("---", unsafe_allow_html=True)
                all_sources = [primary] + related
                st.markdown(
                    f'<span class="detail-label">All Sources ({len(all_sources)})</span>',
                    unsafe_allow_html=True,
                )
                for item in all_sources:
                    date_str = item.published.strftime("%b %d") if item.published else ""
                    st.markdown(
                        f'<p class="related-link"><a href="{item.url}" target="_blank">{item.title}</a>'
                        f' &middot; {item.source} &middot; {date_str} &middot; Score: {item.score}</p>',
                        unsafe_allow_html=True,
                    )

            st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


def main():
    st.set_page_config(page_title="AI News Aggregator", page_icon="📡", layout="wide")
    st.markdown(MINIMALIST_CSS, unsafe_allow_html=True)

    cfg = load_config()
    db = Database(cfg["db_path"])

    # --- Hero + run status ---
    run_stats = db.get_last_run_stats()
    if run_stats:
        last_run = html.escape(str(run_stats.get("last_run", "Unknown")))
        items_added = html.escape(str(run_stats.get("items_added", 0)))
        status_markup = (
            '<div class="status-strip">'
            f'<span class="status-chip status-chip-strong">Last run<strong>{last_run}</strong></span>'
            f'<span class="status-chip">Items added<strong>{items_added}</strong></span>'
            '</div>'
        )
    else:
        status_markup = (
            '<div class="status-strip">'
            '<span class="status-chip">No data yet. Run the pipeline from Settings to get started.</span>'
            '</div>'
        )
    st.markdown(
        '<section class="app-hero">'
        '<p class="hero-eyebrow">AI Signal Desk</p>'
        '<h1>AI News Aggregator</h1>'
        '<p class="hero-sub">Track releases and industry shifts with grouped coverage, score context, and '
        'on-demand learning objectives in one focused view.</p>'
        f'{status_markup}'
        '</section>',
        unsafe_allow_html=True,
    )

    # --- Sidebar filters ---
    st.sidebar.header("Filters")

    score_range = st.sidebar.slider("Score range", 1, 10, (1, 10))

    default_start = datetime.utcnow() - timedelta(days=30)
    date_range = st.sidebar.date_input(
        "Date range",
        value=(default_start.date(), datetime.utcnow().date()),
    )

    start_date = None
    end_date = None
    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        start_date = datetime.combine(date_range[0], datetime.min.time())
        end_date = datetime.combine(date_range[1], datetime.max.time())

    show_acknowledged = st.sidebar.checkbox("Show acknowledged items", value=False)

    sort_options = {"Score": "score", "Date": "published", "Source": "source", "Title": "title"}
    sort_label = st.sidebar.selectbox("Sort by", list(sort_options.keys()))
    sort_dir = st.sidebar.radio("Direction", ["DESC", "ASC"], horizontal=True)

    # --- Tabs ---
    tab_releases, tab_industry, tab_settings, tab_about = st.tabs(
        ["New Releases", "Industry", "Settings", "About"]
    )

    filter_kwargs = dict(
        min_score=score_range[0],
        max_score=score_range[1],
        start_date=start_date,
        end_date=end_date,
        show_acknowledged=show_acknowledged,
        sort_by=sort_options[sort_label],
        sort_dir=sort_dir,
    )

    with tab_releases:
        grouped = db.query_grouped(category="New Releases", **filter_kwargs)
        st.subheader(f"New Releases ({len(grouped)})")
        if not grouped:
            st.markdown(
                '<div class="empty-state">'
                '<div class="icon">&#x1f4e1;</div>'
                '<p>No new release items found matching your filters.</p>'
                '</div>',
                unsafe_allow_html=True,
            )
        else:
            _render_table(grouped, db, cfg)

    with tab_industry:
        grouped = db.query_grouped(category="Industry", **filter_kwargs)
        st.subheader(f"Industry ({len(grouped)})")
        if not grouped:
            st.markdown(
                '<div class="empty-state">'
                '<div class="icon">&#x1f4f0;</div>'
                '<p>No industry items found matching your filters.</p>'
                '</div>',
                unsafe_allow_html=True,
            )
        else:
            _render_table(grouped, db, cfg)

    with tab_settings:
        log_file = PROJECT_ROOT / "data" / "pipeline.log"

        st.markdown('<div class="settings-card">', unsafe_allow_html=True)
        st.subheader("Fetch Pipeline")
        st.markdown(
            '<p class="settings-help">Run the full pipeline: fetch RSS and search, deduplicate, score with Claude, and group.</p>',
            unsafe_allow_html=True,
        )
        if st.button("Run Pipeline", key="run_pipeline", type="primary"):
            with st.status("Running pipeline...", expanded=True) as status:
                log_area = st.empty()
                log_text = ""
                process = subprocess.Popen(
                    [sys.executable, "-u", str(PROJECT_ROOT / "fetch_news.py")],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    cwd=str(PROJECT_ROOT),
                )
                for line in iter(process.stdout.readline, ""):
                    log_text += line
                    log_area.code(log_text)
                process.wait()
                log_file.parent.mkdir(parents=True, exist_ok=True)
                log_file.write_text(log_text)
                if process.returncode == 0:
                    status.update(label="Pipeline complete!", state="complete")
                else:
                    status.update(label="Pipeline failed!", state="error")

        if log_file.exists():
            with st.expander("Pipeline Log", expanded=False):
                st.code(log_file.read_text())
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div class="settings-card">', unsafe_allow_html=True)
        st.subheader("Scoring Settings")
        new_batch_size = st.number_input(
            "Scoring batch size",
            min_value=1, max_value=50, value=cfg.get("scoring_batch_size", 10),
            help="Number of items sent to Claude per API request. Higher = fewer requests but larger prompts.",
        )
        if new_batch_size != cfg.get("scoring_batch_size", 10):
            cfg["scoring_batch_size"] = int(new_batch_size)
            save_config(cfg)

        from ainews.processing.scorer import DEFAULT_SCORING_PROMPT
        current_prompt = cfg.get("scoring_prompt") or DEFAULT_SCORING_PROMPT
        with st.expander("Scoring Prompt", expanded=False):
            st.markdown(
                '<p class="settings-help">The prompt sent to Claude for each batch. Use <code>{items_text}</code> as the placeholder for news items.</p>',
                unsafe_allow_html=True,
            )
            edited_prompt = st.text_area(
                "Scoring prompt",
                value=current_prompt,
                height=400,
                label_visibility="collapsed",
                key="scoring_prompt_editor",
            )
            sp1, sp2 = st.columns([1, 1])
            with sp1:
                if st.button("Save Prompt", key="save_prompt", type="primary"):
                    if "{items_text}" not in edited_prompt:
                        st.error("Prompt must contain {items_text} placeholder.")
                    else:
                        cfg["scoring_prompt"] = edited_prompt
                        save_config(cfg)
                        st.success("Prompt saved.")
            with sp2:
                if st.button("Reset to Default", key="reset_prompt"):
                    cfg.pop("scoring_prompt", None)
                    save_config(cfg)
                    st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div class="settings-card">', unsafe_allow_html=True)
        st.subheader("Learning Objectives Prompt (Opus)")
        current_lo_prompt = cfg.get("lo_prompt") or DEFAULT_LO_PROMPT
        with st.expander("Edit Learning Objectives Prompt", expanded=False):
            st.markdown(
                '<p class="settings-help">Available placeholders: <code>{title}</code>, <code>{source}</code>, <code>{summary}</code>, <code>{url}</code>.</p>',
                unsafe_allow_html=True,
            )
            edited_lo_prompt = st.text_area(
                "LO prompt",
                value=current_lo_prompt,
                height=350,
                label_visibility="collapsed",
                key="lo_prompt_editor",
            )
            lp1, lp2 = st.columns([1, 1])
            with lp1:
                if st.button("Save Prompt", key="save_lo_prompt", type="primary"):
                    required = {"{title}", "{source}", "{summary}", "{url}"}
                    missing = [p for p in required if p not in edited_lo_prompt]
                    if missing:
                        st.error(f"Prompt must contain placeholders: {', '.join(missing)}")
                    else:
                        cfg["lo_prompt"] = edited_lo_prompt
                        save_config(cfg)
                        st.success("Learning objectives prompt saved.")
            with lp2:
                if st.button("Reset to Default", key="reset_lo_prompt"):
                    cfg.pop("lo_prompt", None)
                    save_config(cfg)
                    st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div class="settings-card">', unsafe_allow_html=True)
        st.subheader("Smart Grouper")
        st.markdown(
            '<p class="settings-help">Re-analyze all items and group related news coverage together.</p>',
            unsafe_allow_html=True,
        )
        if st.button("Run Smart Grouper", key="run_grouper", type="primary"):
            with st.spinner("Grouping items..."):
                count = run_grouper(db)
            st.success(f"Done — created {count} groups.")
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        feeds = cfg.get("feeds", [])
        rss_feeds = [(i, f) for i, f in enumerate(feeds) if f.get("type", "auto") in ("rss", "auto")]
        web_feeds = [(i, f) for i, f in enumerate(feeds) if f.get("type") == "web"]

        st.markdown('<div class="settings-card">', unsafe_allow_html=True)
        st.subheader("RSS & Auto-Detect Feeds")
        st.markdown(
            '<p class="settings-help">Fetched via feedparser (rss) or httpx with auto-detection (auto). These use standard HTTP requests.</p>',
            unsafe_allow_html=True,
        )
        for idx, feed in rss_feeds:
            feed_type = feed.get("type", "auto")
            is_enabled = feed.get("enabled", True)
            st.markdown('<div class="settings-feed-row">', unsafe_allow_html=True)
            c_toggle, c_type, c_name, c_url, c_rm = st.columns([0.4, 0.8, 2.5, 5, 0.4])
            with c_toggle:
                enabled = st.toggle(
                    "on", value=is_enabled,
                    key=f"toggle_rss_{idx}", label_visibility="collapsed",
                )
                if enabled != is_enabled:
                    cfg["feeds"][idx]["enabled"] = enabled
                    save_config(cfg)
                    st.rerun()
            c_type.markdown(
                f'<span class="meta-pill">{feed_type}</span>',
                unsafe_allow_html=True,
            )
            name_cls = "feed-name" if is_enabled else "feed-name feed-disabled"
            url_cls = "feed-url" if is_enabled else "feed-url feed-disabled"
            c_name.markdown(f'<span class="{name_cls}">{feed["name"]}</span>', unsafe_allow_html=True)
            c_url.markdown(f'<span class="{url_cls}">{feed["url"]}</span>', unsafe_allow_html=True)
            with c_rm:
                if st.button("✕", key=f"rm_feed_{idx}"):
                    cfg["feeds"].pop(idx)
                    save_config(cfg)
                    st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

        with st.container():
            st.markdown("**Add RSS / Auto Feed**")
            ar1, ar2, ar3, ar4 = st.columns([2, 2.5, 4.5, 1])
            new_rss_type = ar1.selectbox("Type", ["auto", "rss"], key="new_rss_type", label_visibility="collapsed")
            new_rss_name = ar2.text_input("Name", key="new_rss_name", label_visibility="collapsed", placeholder="Feed name")
            new_rss_url = ar3.text_input("URL", key="new_rss_url", label_visibility="collapsed", placeholder="https://example.com/feed.xml")
            with ar4:
                if st.button("Add", key="add_rss_feed", type="primary"):
                    if new_rss_name and new_rss_url:
                        entry = {"name": new_rss_name, "url": new_rss_url, "enabled": True}
                        if new_rss_type == "rss":
                            entry["type"] = "rss"
                        cfg.setdefault("feeds", []).append(entry)
                        save_config(cfg)
                        st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div class="settings-card">', unsafe_allow_html=True)
        st.subheader("Websites (Browser Scraping)")
        st.markdown(
            '<p class="settings-help">Fetched via headless browser (Playwright) for JS-rendered pages that block simple HTTP requests.</p>',
            unsafe_allow_html=True,
        )
        for idx, feed in web_feeds:
            is_enabled = feed.get("enabled", True)
            st.markdown('<div class="settings-feed-row">', unsafe_allow_html=True)
            c_toggle, c_name, c_url, c_rm = st.columns([0.4, 3, 5.2, 0.4])
            with c_toggle:
                enabled = st.toggle(
                    "on", value=is_enabled,
                    key=f"toggle_web_{idx}", label_visibility="collapsed",
                )
                if enabled != is_enabled:
                    cfg["feeds"][idx]["enabled"] = enabled
                    save_config(cfg)
                    st.rerun()
            name_cls = "feed-name" if is_enabled else "feed-name feed-disabled"
            url_cls = "feed-url" if is_enabled else "feed-url feed-disabled"
            c_name.markdown(f'<span class="{name_cls}">{feed["name"]}</span>', unsafe_allow_html=True)
            c_url.markdown(f'<span class="{url_cls}">{feed["url"]}</span>', unsafe_allow_html=True)
            with c_rm:
                if st.button("✕", key=f"rm_feed_{idx}"):
                    cfg["feeds"].pop(idx)
                    save_config(cfg)
                    st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

        with st.container():
            st.markdown("**Add Website**")
            aw1, aw2, aw3 = st.columns([3, 5.5, 1])
            new_web_name = aw1.text_input("Name", key="new_web_name", label_visibility="collapsed", placeholder="Site name")
            new_web_url = aw2.text_input("URL", key="new_web_url", label_visibility="collapsed", placeholder="https://example.com/news/")
            with aw3:
                if st.button("Add", key="add_web_feed", type="primary"):
                    if new_web_name and new_web_url:
                        cfg.setdefault("feeds", []).append({"name": new_web_name, "url": new_web_url, "type": "web", "enabled": True})
                        save_config(cfg)
                        st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div class="settings-card">', unsafe_allow_html=True)
        st.subheader("Search Queries")
        queries = cfg.get("search_queries", [])
        for i, q in enumerate(queries):
            c_q, c_rm = st.columns([9, 1])
            c_q.markdown(f'<span class="query-text">{q}</span>', unsafe_allow_html=True)
            with c_rm:
                if st.button("✕", key=f"rm_query_{i}", type="primary"):
                    cfg["search_queries"].pop(i)
                    save_config(cfg)
                    st.rerun()

        with st.container():
            st.markdown("**Add Search Query**")
            aq1, aq2 = st.columns([9, 1])
            new_query = aq1.text_input("Query", key="new_query", label_visibility="collapsed", placeholder="e.g. OpenAI news")
            with aq2:
                if st.button("Add", key="add_query", type="primary"):
                    if new_query:
                        cfg.setdefault("search_queries", []).append(new_query)
                        save_config(cfg)
                        st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div class="settings-card">', unsafe_allow_html=True)
        st.subheader("Source Scan History")
        source_status = db.get_source_status()
        if not source_status:
            st.info("No scan data yet. Run the fetch pipeline to populate.")
        else:
            st.markdown('<div class="news-table">', unsafe_allow_html=True)
            st.markdown('<div class="table-header">', unsafe_allow_html=True)
            h_src, h_count, h_last = st.columns([4, 2, 4])
            h_src.markdown("**Source**")
            h_count.markdown("**Items**")
            h_last.markdown("**Last Scanned**")
            st.markdown('</div>', unsafe_allow_html=True)
            for s in source_status:
                st.markdown('<div class="settings-feed-row">', unsafe_allow_html=True)
                c_src, c_count, c_last = st.columns([4, 2, 4])
                c_src.markdown(f'<span class="feed-name">{s["source"]}</span>', unsafe_allow_html=True)
                c_count.markdown(f'<span class="query-text">{s["item_count"]}</span>', unsafe_allow_html=True)
                c_last.markdown(f'<span class="table-muted">{s["last_scanned"]}</span>', unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with tab_about:
        st.markdown('<div class="about-section">', unsafe_allow_html=True)
        st.markdown("""
### AI News Aggregator

A curated AI news dashboard that aggregates, scores, and groups news from the leading AI
companies using Claude AI. Built to cut through the noise and surface what matters for
educational video production.

---

### Pipeline

The fetch pipeline runs in five stages, triggered from the Settings tab or via the command line:

1. **Fetch** — Pulls news from all enabled sources. Three fetcher types are supported:
   - **RSS / Atom** — parsed directly with `feedparser`
   - **Auto-detect** — fetches the page with `httpx`, auto-discovers an RSS feed if available,
     and falls back to HTML scraping if not
   - **Website (browser)** — renders JavaScript-heavy pages in a headless Chromium browser
     via Playwright, then scrapes links and titles from the rendered DOM
2. **Deduplicate** — URLs are normalized (tracking params stripped, hosts lowercased) and
   compared. Titles are then fuzzy-matched (Levenshtein ratio) to catch near-duplicates that
   share different URLs.
3. **Score** — Items are sent to **Claude Sonnet** in batches. For each item Claude returns
   a relevance score (1\u201310), a category (*New Releases* or *Industry*), a summary, score
   reasoning, and initial learning objectives. The scoring prompt is fully customizable from
   the Settings tab.
4. **Group** — The smart grouper clusters articles covering the same story by extracting
   significant words from titles and fuzzy-matching them. Vendor sources (OpenAI, Anthropic,
   Google, etc.) are preferred as the primary link in each group.
5. **Store** — Results are written to a local SQLite database with automatic schema migrations.

---

### Dashboard

- **New Releases** and **Industry** tabs separate product launches from broader news
- **Sidebar filters** — score range, date range, sort order, and acknowledged-item visibility
- **Expandable rows** — click any row to reveal the full summary, score reasoning, learning
  objectives, metadata pills, and grouped source links
- **Acknowledge** — mark items as read; acknowledged items are hidden by default
- **Score badges** — color-coded (red \u2265 8, orange \u2265 5, muted below) with a subtle
  glow on high-impact items
- **Row hover highlights** and **animated detail panels** (fade + slide) for a polished feel

---

### Learning Objectives with Opus

Each news item can have its learning objectives regenerated on demand using **Claude Opus**.
Click **Generate With Opus** inside any expanded row to:

- Send the item\u2019s title, source, summary, and URL to Opus with a curriculum-design prompt
- Receive 3\u20135 concise, actionable learning objectives (starting with action verbs)
- Existing objectives are greyed out while generating, with an animated loading indicator
- Once generated, the button is replaced with a **Generated with Opus** badge
- The prompt is fully editable from the Settings tab

---

### Source Management

- **Enable / disable** individual feeds and website scrapes with the toggle switch on the
  Settings tab. Disabled sources are skipped during pipeline runs without being removed.
- **Add / remove** RSS feeds, auto-detect feeds, website scrapes, and DuckDuckGo search
  queries directly from the dashboard.
- **Source Scan History** shows the item count and last-scanned timestamp for each source.

---

### Settings

All configuration is managed from the Settings tab:

| Setting | Description |
|---|---|
| **Run Pipeline** | Execute the full fetch\u2013score\u2013group pipeline with live log output |
| **Scoring batch size** | Items per Claude API request (higher = fewer requests) |
| **Scoring Prompt** | The prompt sent to Sonnet for scoring \u2014 fully editable with reset |
| **Learning Objectives Prompt** | The prompt sent to Opus for generating objectives |
| **Smart Grouper** | Re-run the grouper manually to rebuild story clusters |
| **Feeds & Websites** | Add, remove, and enable/disable sources |
| **Search Queries** | Add or remove DuckDuckGo search queries |

---

### Tech Stack

| Component | Technology |
|---|---|
| **Scoring** | Claude Sonnet 4.5 via Anthropic API |
| **Learning Objectives** | Claude Opus 4.6 via Anthropic API |
| **Dashboard** | Streamlit with a custom minimalist design system |
| **Database** | SQLite with automatic schema migrations |
| **RSS parsing** | `feedparser` |
| **HTTP client** | `httpx` |
| **Browser scraping** | Playwright (headless Chromium) |
| **Search** | DuckDuckGo via `duckduckgo_search` |
| **Deduplication** | URL normalization + `thefuzz` (Levenshtein distance) |
| **Fuzzy grouping** | Token-sort ratio with significant-word overlap |
""")
        st.markdown('</div>', unsafe_allow_html=True)

    db.close()


if __name__ == "__main__":
    main()
