#!/usr/bin/env python3
"""AI News Aggregator — Streamlit Dashboard (Pluralsight theme)."""

import subprocess
import sys
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

PLURALSIGHT_CSS = """
<style>
    /* ---- Global ---- */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    .stApp, [data-testid="stAppViewContainer"] {
        background-color: #130f25;
        color: #ffffff;
        font-family: 'Inter', 'Helvetica Neue', Helvetica, Arial, sans-serif;
    }

    /* ---- Animations ---- */
    @keyframes fadeSlideDown {
        from {
            opacity: 0;
            transform: translateY(-6px);
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

    /* Sidebar */
    [data-testid="stSidebar"], [data-testid="stSidebar"] > div {
        background-color: #1e1a36;
        color: #ffffff;
    }
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] .stMarkdown,
    [data-testid="stSidebar"] span {
        color: #ffffff !important;
    }
    [data-testid="stSidebar"] [data-testid="stWidgetLabel"] label {
        color: #a5aacf !important;
    }

    /* Header / title */
    h1 { color: #ffffff !important; font-weight: 700; letter-spacing: -0.02em; }
    h2, h3 { color: #ffffff !important; font-weight: 600; }

    /* Links — pink accent */
    a { color: #e7005e !important; text-decoration: none; transition: color 0.15s ease; }
    a:hover { color: #ff1675 !important; }

    /* Tabs */
    [data-testid="stTabs"] button {
        color: #a5aacf !important;
        font-weight: 500;
        border-bottom: 2px solid transparent;
        transition: color 0.15s ease, border-color 0.15s ease;
    }
    [data-testid="stTabs"] button[aria-selected="true"] {
        color: #e7005e !important;
        border-bottom: 2px solid #e7005e !important;
    }
    [data-testid="stTabs"] button:hover {
        color: #ffffff !important;
    }

    /* Dividers */
    hr { border-color: #383461 !important; }

    /* Text inputs */
    input[type="text"], textarea {
        background-color: #2a2753 !important;
        color: #ffffff !important;
        border: 1px solid #383461 !important;
        border-radius: 8px !important;
        transition: border-color 0.15s ease;
    }
    input[type="text"]:focus, textarea:focus {
        border-color: #e7005e !important;
    }

    /* ---- Buttons ---- */

    /* Base: all buttons transparent/ghost by default */
    .stButton > button {
        background: transparent !important;
        background-color: transparent !important;
        color: #a5aacf !important;
        border: none !important;
        border-radius: 999px !important;
        font-weight: 600;
        padding: 0.3rem 1.2rem !important;
        box-shadow: none !important;
        transition: color 0.15s ease, background-color 0.15s ease;
    }
    .stButton > button:hover {
        color: #ffffff !important;
    }
    .stButton > button:focus {
        box-shadow: none !important;
        outline: none !important;
    }

    /* Primary action buttons — pink */
    .stButton > button[kind="primary"],
    .stButton > button[kind="primary"]:focus {
        background-color: #e7005e !important;
        color: #ffffff !important;
        border: none !important;
        border-radius: 6px !important;
        padding: 0.2rem 0.8rem !important;
        font-size: 0.8rem !important;
        transition: background-color 0.15s ease, transform 0.1s ease;
    }
    .stButton > button[kind="primary"]:hover {
        background-color: #ff1675 !important;
        color: #ffffff !important;
        transform: translateY(-1px);
    }
    .stButton > button[kind="primary"]:active {
        transform: translateY(0);
    }

    /* Ack badge (acknowledged items) — static grey pill */
    .ack-done-badge {
        display: inline-block;
        background-color: #2a2753;
        color: #555;
        padding: 0.1rem 0.6rem;
        border-radius: 6px;
        font-size: 0.75rem;
        font-weight: 500;
        line-height: 1.3;
    }

    /* Selectbox / radio / slider */
    [data-testid="stSelectbox"] > div > div,
    [data-baseweb="select"] {
        background-color: #2a2753 !important;
        color: #ffffff !important;
    }

    /* Toggle switch — pink accent */
    [data-testid="stToggle"] label span[data-testid="stToggleLabel"] {
        color: #a5aacf !important;
    }

    /* Info boxes */
    [data-testid="stAlert"] {
        background-color: #1e1a36 !important;
        color: #a5aacf !important;
        border: 1px solid #383461 !important;
        border-radius: 8px !important;
    }

    /* Status bar text */
    .run-status {
        color: #a5aacf;
        font-size: 0.85rem;
        padding: 0.4rem 0 0.8rem 0;
    }
    .run-status strong { color: #ffffff; }

    /* ---- News Table ---- */

    /* Table header row */
    .table-header {
        background-color: #1e1a36;
        border-radius: 8px 8px 0 0;
        border-bottom: 2px solid #383461;
        padding: 0.5rem 0;
        margin-bottom: 0;
    }
    .table-header p, .table-header span {
        color: #a5aacf !important;
        font-weight: 600 !important;
        font-size: 0.75rem !important;
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }

    /* News row container */
    .news-row {
        border-bottom: 1px solid rgba(56, 52, 97, 0.4);
        padding: 0.15rem 0;
        transition: background-color 0.15s ease;
        border-radius: 4px;
        margin: 0 -0.25rem;
        padding-left: 0.25rem;
        padding-right: 0.25rem;
    }
    .news-row:hover {
        background-color: rgba(30, 26, 54, 0.7);
    }

    /* Row content */
    .news-row p, .news-row span, .news-row div {
        font-size: 0.85rem !important;
        color: #ffffff !important;
        margin-bottom: 0 !important;
        padding-bottom: 0 !important;
    }
    .news-row a { font-size: 0.85rem !important; }

    /* Expand/collapse arrow button */
    .news-row .stButton > button {
        font-size: 0.65rem !important;
        padding: 0.15rem 0.5rem !important;
        min-height: 0 !important;
        line-height: 1 !important;
        color: #a5aacf !important;
        border-radius: 4px !important;
        transition: color 0.15s ease, background-color 0.15s ease;
    }
    .news-row .stButton > button:hover {
        color: #e7005e !important;
        background-color: rgba(231, 0, 94, 0.1) !important;
    }

    /* Remove extra padding in columns */
    [data-testid="stHorizontalBlock"] {
        gap: 0.3rem !important;
        align-items: center !important;
    }

    /* Tighter vertical spacing */
    [data-testid="stVerticalBlock"] > div {
        padding-top: 0 !important;
        padding-bottom: 0 !important;
    }
    .news-row [data-testid="stHorizontalBlock"] {
        padding: 0.05rem 0 !important;
        min-height: 1.6rem !important;
    }

    /* Score badge */
    .score-badge {
        display: inline-block;
        font-weight: 700;
        font-size: 0.85rem;
        color: #ffffff;
        border-radius: 6px;
        padding: 0.15rem 0.55rem;
        text-align: center;
        min-width: 2rem;
        line-height: 1.4;
    }
    .score-badge.score-high {
        box-shadow: 0 0 8px rgba(211, 47, 47, 0.3);
    }
    .score-badge.score-mid {
        box-shadow: 0 0 6px rgba(243, 156, 18, 0.2);
    }

    /* Detail panel — animated */
    .detail-panel {
        background-color: #1e1a36;
        border-left: 3px solid #e7005e;
        border-radius: 0 8px 8px 0;
        padding: 1rem 1.2rem;
        margin: 0.2rem 0 0.5rem 1.8rem;
        animation: fadeSlideDown 0.25s ease-out;
    }
    .detail-panel p {
        color: #a5aacf !important;
        font-size: 0.82rem !important;
        line-height: 1.6 !important;
    }
    .detail-panel strong { color: #ffffff !important; }

    /* Detail panel labels */
    .detail-label {
        display: inline-block;
        color: #a5aacf;
        font-size: 0.7rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        margin-bottom: 0.2rem;
    }

    /* Related items in detail panel */
    .related-link {
        color: #a5aacf !important;
        font-size: 0.8rem !important;
        padding: 0.2rem 0;
        border-bottom: 1px solid rgba(56, 52, 97, 0.3);
        margin-bottom: 0;
    }
    .related-link:last-child { border-bottom: none; }
    .related-link a { color: #e7005e !important; font-size: 0.8rem !important; }
    .related-count {
        background-color: #2a2753;
        color: #a5aacf;
        border-radius: 4px;
        padding: 0.05rem 0.4rem;
        font-size: 0.7rem;
        font-weight: 600;
        margin-left: 0.3rem;
        vertical-align: middle;
    }

    /* Metadata pills in detail panel */
    .meta-pill {
        display: inline-block;
        background-color: #2a2753;
        color: #a5aacf;
        border-radius: 4px;
        padding: 0.1rem 0.5rem;
        font-size: 0.75rem;
        font-weight: 500;
        margin-right: 0.4rem;
        margin-top: 0.4rem;
    }
    .meta-pill strong { color: #ffffff !important; font-size: 0.75rem !important; }

    /* ---- Settings page ---- */

    /* Settings feed rows */
    .settings-feed-row {
        border-bottom: 1px solid rgba(56, 52, 97, 0.3);
        padding: 0.2rem 0;
    }

    /* ---- About page ---- */
    .about-section {
        color: #a5aacf !important;
        line-height: 1.7;
    }
    .about-section h3 { color: #ffffff !important; margin-top: 1.5rem !important; }
    .about-section strong { color: #ffffff !important; }
    .about-section code {
        background-color: #2a2753 !important;
        color: #e7005e !important;
        padding: 0.1rem 0.4rem;
        border-radius: 4px;
        font-size: 0.85rem;
    }

    /* ---- Empty state ---- */
    .empty-state {
        text-align: center;
        padding: 3rem 1rem;
        color: #a5aacf;
    }
    .empty-state .icon {
        font-size: 2.5rem;
        margin-bottom: 0.5rem;
        opacity: 0.5;
    }

    /* ---- Learning objectives generation ---- */
    .lo-stale {
        opacity: 0.25;
        transition: opacity 0.3s ease;
    }
    @keyframes pulse {
        0%, 100% { opacity: 0.4; }
        50% { opacity: 1; }
    }
    .lo-generating-indicator {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        color: #e7005e;
        font-size: 0.8rem;
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
        background-color: #e7005e;
        animation: pulse 1.5s ease-in-out infinite;
    }
    .lo-generating-indicator .dot-loader span:nth-child(2) { animation-delay: 0.2s; }
    .lo-generating-indicator .dot-loader span:nth-child(3) { animation-delay: 0.4s; }

    /* "Generated with Opus" badge */
    .lo-opus-badge {
        display: inline-block;
        background-color: #2a2753;
        color: #a5aacf;
        font-size: 0.45rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        padding: 0.1rem 0.5rem;
        border-radius: 4px;
        margin-top: 0.15rem;
    }

    /* Generate button — identical to .lo-opus-badge */
    /* :has() targets the button via a marker in the same stHorizontalBlock */
    [data-testid="stHorizontalBlock"]:has(.lo-btn-marker) .stButton {
        display: inline-block !important;
        width: auto !important;
    }
    [data-testid="stHorizontalBlock"]:has(.lo-btn-marker) .stButton > button {
        background-color: #2a2753 !important;
        color: #a5aacf !important;
        border: none !important;
        border-radius: 4px !important;
        font-family: 'Inter', 'Helvetica Neue', Helvetica, Arial, sans-serif !important;
        font-size: 0.45rem !important;
        font-weight: 600 !important;
        text-transform: uppercase !important;
        letter-spacing: 0.06em !important;
        padding: 0.1rem 0.5rem !important;
        min-height: 0 !important;
        height: auto !important;
        line-height: 1.2 !important;
        margin: 0 !important;
        transition: background-color 0.15s ease, color 0.15s ease;
    }
    [data-testid="stHorizontalBlock"]:has(.lo-btn-marker) .stButton > button:hover {
        background-color: #383461 !important;
        color: #ffffff !important;
    }
</style>
"""


def score_color(score: int) -> str:
    if score >= 8:
        return "#d32f2f"  # red
    elif score >= 5:
        return "#f39c12"  # orange
    else:
        return "#a5aacf"  # muted


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

        color = score_color(primary.score)
        score_cls = "score-high" if primary.score >= 8 else ("score-mid" if primary.score >= 5 else "")
        c_score.markdown(
            f'<span class="score-badge {score_cls}" style="background-color:{color};">{primary.score}</span>',
            unsafe_allow_html=True,
        )

        # Title with related count badge
        title_html = f"[{primary.title}]({primary.url})"
        if related:
            title_html += f' <span class="related-count">+{len(related)}</span>'
        c_title.markdown(title_html, unsafe_allow_html=True)

        c_source.markdown(f'<span style="color:#a5aacf;">{primary.source}</span>', unsafe_allow_html=True)
        c_date.markdown(
            f'<span style="color:#a5aacf;">{primary.published.strftime("%b %d") if primary.published else "\u2014"}</span>',
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
                        '<span style="color:#555;font-size:0.8rem;font-style:italic;">'
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


def main():
    st.set_page_config(page_title="AI News Aggregator", page_icon="📡", layout="wide")
    st.markdown(PLURALSIGHT_CSS, unsafe_allow_html=True)
    st.title("AI News Aggregator")

    cfg = load_config()
    db = Database(cfg["db_path"])

    # --- Run status bar ---
    run_stats = db.get_last_run_stats()
    if run_stats:
        st.markdown(
            f'<div class="run-status">Last run: <strong>{run_stats["last_run"]}</strong> · '
            f'Items added: <strong>{run_stats["items_added"]}</strong></div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="run-status">No data yet — run the fetch pipeline to get started.</div>',
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
        # --- Pipeline Runner ---
        st.subheader("Fetch Pipeline")
        st.markdown(
            '<span style="color:#a5aacf;font-size:0.85rem;">'
            "Run the full pipeline: fetch RSS &amp; search, deduplicate, score with Claude, and group."
            "</span>",
            unsafe_allow_html=True,
        )
        log_file = PROJECT_ROOT / "data" / "pipeline.log"
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
                # Save log to file
                log_file.parent.mkdir(parents=True, exist_ok=True)
                log_file.write_text(log_text)
                if process.returncode == 0:
                    status.update(label="Pipeline complete!", state="complete")
                else:
                    status.update(label="Pipeline failed!", state="error")

        # --- Pipeline Log ---
        if log_file.exists():
            with st.expander("Pipeline Log", expanded=False):
                st.code(log_file.read_text())

        st.divider()

        # --- Scoring Settings ---
        st.subheader("Scoring Settings")
        new_batch_size = st.number_input(
            "Scoring batch size",
            min_value=1, max_value=50, value=cfg.get("scoring_batch_size", 10),
            help="Number of items sent to Claude per API request. Higher = fewer requests but larger prompts.",
        )
        if new_batch_size != cfg.get("scoring_batch_size", 10):
            cfg["scoring_batch_size"] = int(new_batch_size)
            save_config(cfg)

        # --- Scoring Prompt ---
        from ainews.processing.scorer import DEFAULT_SCORING_PROMPT
        current_prompt = cfg.get("scoring_prompt") or DEFAULT_SCORING_PROMPT
        with st.expander("Scoring Prompt", expanded=False):
            st.markdown(
                '<span style="color:#a5aacf;font-size:0.85rem;">'
                "The prompt sent to Claude for each batch. Use <code>{items_text}</code> as the placeholder for news items."
                "</span>",
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

        st.divider()

        # --- Learning Objectives Prompt ---
        current_lo_prompt = cfg.get("lo_prompt") or DEFAULT_LO_PROMPT
        with st.expander("Learning Objectives Prompt (Opus)", expanded=False):
            st.markdown(
                '<span style="color:#a5aacf;font-size:0.85rem;">'
                "The prompt sent to Claude Opus when generating learning objectives. "
                "Available placeholders: <code>{title}</code>, <code>{source}</code>, "
                "<code>{summary}</code>, <code>{url}</code>."
                "</span>",
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

        st.divider()

        # --- Smart Grouper ---
        st.subheader("Smart Grouper")
        st.markdown(
            '<span style="color:#a5aacf;font-size:0.85rem;">'
            "Re-analyze all items and group related news coverage together."
            "</span>",
            unsafe_allow_html=True,
        )
        if st.button("Run Smart Grouper", key="run_grouper", type="primary"):
            with st.spinner("Grouping items..."):
                count = run_grouper(db)
            st.success(f"Done — created {count} groups.")
            st.rerun()

        st.divider()

        # --- Sources Management (split by type) ---
        feeds = cfg.get("feeds", [])
        rss_feeds = [(i, f) for i, f in enumerate(feeds) if f.get("type", "auto") in ("rss", "auto")]
        web_feeds = [(i, f) for i, f in enumerate(feeds) if f.get("type") == "web"]

        # -- RSS & Auto-Detect Feeds --
        st.subheader("RSS & Auto-Detect Feeds")
        st.markdown(
            '<span style="color:#a5aacf;font-size:0.85rem;">'
            "Fetched via feedparser (rss) or httpx with auto-detection (auto). These use standard HTTP requests."
            "</span>",
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
            name_color = "#ffffff" if is_enabled else "#555"
            c_name.markdown(f'<span style="color:{name_color};font-weight:500;">{feed["name"]}</span>', unsafe_allow_html=True)
            url_color = "#a5aacf" if is_enabled else "#444"
            c_url.markdown(f'<span style="color:{url_color};font-size:0.8rem;">{feed["url"]}</span>', unsafe_allow_html=True)
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

        st.divider()

        # -- Website Feeds (Browser Scraping) --
        st.subheader("Websites (Browser Scraping)")
        st.markdown(
            '<span style="color:#a5aacf;font-size:0.85rem;">'
            "Fetched via headless browser (Playwright) for JS-rendered pages that block simple HTTP requests."
            "</span>",
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
            name_color = "#ffffff" if is_enabled else "#555"
            c_name.markdown(f'<span style="color:{name_color};font-weight:500;">{feed["name"]}</span>', unsafe_allow_html=True)
            url_color = "#a5aacf" if is_enabled else "#444"
            c_url.markdown(f'<span style="color:{url_color};font-size:0.8rem;">{feed["url"]}</span>', unsafe_allow_html=True)
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

        st.divider()

        # --- Search Queries Management ---
        st.subheader("Search Queries")
        queries = cfg.get("search_queries", [])
        for i, q in enumerate(queries):
            c_q, c_rm = st.columns([9, 1])
            c_q.markdown(f'<span style="color:#ffffff;">{q}</span>', unsafe_allow_html=True)
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

        st.divider()

        # --- Source scan status ---
        st.subheader("Source Scan History")
        source_status = db.get_source_status()
        if not source_status:
            st.info("No scan data yet. Run the fetch pipeline to populate.")
        else:
            st.markdown('<div class="table-header">', unsafe_allow_html=True)
            h_src, h_count, h_last = st.columns([4, 2, 4])
            h_src.markdown("**Source**")
            h_count.markdown("**Items**")
            h_last.markdown("**Last Scanned**")
            st.markdown('</div>', unsafe_allow_html=True)
            for s in source_status:
                st.markdown('<div class="settings-feed-row">', unsafe_allow_html=True)
                c_src, c_count, c_last = st.columns([4, 2, 4])
                c_src.markdown(f'<span style="color:#ffffff;font-weight:500;">{s["source"]}</span>', unsafe_allow_html=True)
                c_count.markdown(f'<span style="color:#ffffff;">{s["item_count"]}</span>', unsafe_allow_html=True)
                c_last.markdown(f'<span style="color:#a5aacf;font-size:0.8rem;">{s["last_scanned"]}</span>', unsafe_allow_html=True)
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
| **Dashboard** | Streamlit with custom Pluralsight-inspired dark theme |
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
