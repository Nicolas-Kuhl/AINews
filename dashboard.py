#!/usr/bin/env python3
"""AI News Aggregator — Streamlit Dashboard (Rebuilt with best practices)."""

import streamlit as st
from datetime import datetime, timedelta, timezone
from pathlib import Path
import yaml

from ainews.config import load_config
from ainews.storage.database import Database
from dashboard_components import _render_news_list, _render_digest, _render_settings_tab, load_css

PROJECT_ROOT = Path(__file__).resolve().parent


@st.cache_data(ttl=60)  # Cache for 60 seconds
def get_grouped_items(db_path: str, category: str, **filter_kwargs):
    """Cached database query for grouped items."""
    db = Database(db_path)
    result = db.query_grouped(category=category, **filter_kwargs)
    db.close()
    return result


@st.cache_data(ttl=60)
def get_digest_items(db_path: str, min_score: int, max_score: int, show_acknowledged: bool, limit_days: int, start_date=None, end_date=None):
    """Cached database query for daily digest view."""
    db = Database(db_path)
    result = db.query_by_day(
        min_score=min_score, max_score=max_score,
        show_acknowledged=show_acknowledged, limit_days=limit_days,
        start_date=start_date, end_date=end_date,
    )
    db.close()
    return result


@st.cache_data(ttl=60)  # Cache for 60 seconds
def get_last_run_stats(db_path: str):
    """Cached database query for run stats."""
    db = Database(db_path)
    result = db.get_last_run_stats()
    db.close()
    return result


@st.cache_data(ttl=60)
def get_source_status(db_path: str):
    """Cached source status data for dashboard health cards."""
    db = Database(db_path)
    result = db.get_source_status()
    db.close()
    return result


def _relative_time_label(timestamp_iso: str) -> str:
    """Format an ISO timestamp as a compact relative label."""
    try:
        dt = datetime.fromisoformat(timestamp_iso)
        now = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = now - dt
        if delta.total_seconds() < 60:
            return "just now"
        if delta.total_seconds() < 3600:
            mins = int(delta.total_seconds() // 60)
            return f"{mins} minute{'s' if mins != 1 else ''} ago"
        if delta.total_seconds() < 86400:
            hours = int(delta.total_seconds() // 3600)
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        days = int(delta.total_seconds() // 86400)
        return f"{days} day{'s' if days != 1 else ''} ago"
    except Exception:
        return timestamp_iso


def _matches_search(item, query_lower: str) -> bool:
    """Return True when query matches key story fields."""
    haystacks = [
        item.title or "",
        item.summary or "",
        item.source or "",
        item.category or "",
    ]
    return any(query_lower in text.lower() for text in haystacks)


def filter_grouped_items(grouped_items, search_query: str):
    """Filter grouped items by search query."""
    if not search_query:
        return grouped_items

    query_lower = search_query.lower()
    filtered = []

    for primary, related in grouped_items:
        if _matches_search(primary, query_lower):
            filtered.append((primary, related))
            continue

        for item in related:
            if _matches_search(item, query_lower):
                filtered.append((primary, related))
                break

    return filtered


def _count_grouped_items(grouped_items) -> int:
    """Count primary and related items in a grouped result set."""
    return sum(1 + len(related) for _, related in grouped_items)


def check_authentication():
    """Check if authentication is enabled and handle login."""
    auth_config_path = PROJECT_ROOT / "auth_config.yaml"

    # If no auth config exists, skip authentication
    if not auth_config_path.exists():
        return True

    # Import authenticator only if config exists
    try:
        import streamlit_authenticator as stauth
    except ImportError:
        st.error("streamlit-authenticator not installed. Run: pip install streamlit-authenticator")
        st.stop()

    # Load auth config
    with open(auth_config_path) as file:
        auth_config = yaml.safe_load(file)

    # Create authenticator
    authenticator = stauth.Authenticate(
        auth_config['credentials'],
        auth_config['cookie']['name'],
        auth_config['cookie']['key'],
        auth_config['cookie']['expiry_days']
    )

    # Login form (new API - uses session state)
    try:
        authenticator.login(location='main')
    except Exception as e:
        st.error(f"Authentication error: {e}")
        st.stop()

    # Check authentication status from session state
    authentication_status = st.session_state.get('authentication_status')
    name = st.session_state.get('name')
    username = st.session_state.get('username')

    if authentication_status == False:
        st.error('Username/password is incorrect')
        st.stop()
    elif authentication_status == None:
        st.warning('Please enter your username and password')
        st.info('💡 **First time?** Copy `auth_config.example.yaml` to `auth_config.yaml` and customize it.')
        st.stop()

    # Add logout button in sidebar if authenticated
    if authentication_status:
        with st.sidebar:
            st.write(f'Welcome **{name}**')
            authenticator.logout(location='sidebar')

    return True


def main():
    st.set_page_config(page_title="AINews", page_icon="📡", layout="wide")

    # Check authentication
    check_authentication()

    # Load CSS from external file
    load_css(PROJECT_ROOT / "assets" / "style.css")

    cfg = load_config()
    db = Database(cfg["db_path"])

    run_stats = get_last_run_stats(cfg["db_path"])
    source_status = get_source_status(cfg["db_path"])
    enabled_sources = sum(1 for feed in cfg.get("feeds", []) if feed.get("enabled", True))
    enabled_queries = len(cfg.get("search_queries", []))
    total_sources = enabled_sources + enabled_queries

    stale_sources = 0
    if run_stats:
        try:
            last_run_dt = datetime.fromisoformat(run_stats["last_run"])
            if last_run_dt.tzinfo is None:
                last_run_dt = last_run_dt.replace(tzinfo=timezone.utc)
            for source in source_status:
                try:
                    scanned = datetime.fromisoformat(source["last_scanned"])
                    if scanned.tzinfo is None:
                        scanned = scanned.replace(tzinfo=timezone.utc)
                    if scanned < last_run_dt - timedelta(days=2):
                        stale_sources += 1
                except Exception:
                    stale_sources += 1
        except Exception:
            stale_sources = 0

    st.markdown(
        '<section class="hero-shell terminal-deck">'
        '<div class="terminal-deck-bar">'
        '<span class="terminal-node">AINEWS // ANALYST TERMINAL</span>'
        '<span class="terminal-node terminal-node-live">LIVE MONITOR</span>'
        '</div>'
        '<div class="terminal-deck-main">'
        '<div class="hero-copy">'
        '<p class="hero-kicker">Operations View</p>'
        '<h1>AI News Analyst Terminal</h1>'
        '<p class="hero-subtitle">Fast, high-signal scanning for releases, research, business moves, and developer tooling.</p>'
        '</div>'
        '<div class="terminal-legend">'
        '<span class="legend-item"><span class="legend-swatch legend-cyan"></span>active state</span>'
        '<span class="legend-item"><span class="legend-swatch legend-amber"></span>high score</span>'
        '<span class="legend-item"><span class="legend-swatch legend-red"></span>alert</span>'
        '</div>'
        '</div>'
        '</section>',
        unsafe_allow_html=True,
    )

    if run_stats:
        st.markdown(
            '<section class="overview-grid">'
            f'<div class="overview-card overview-card-wide">'
            f'<p class="overview-label">Pipeline status</p>'
            f'<div class="overview-value">ONLINE</div>'
            f'<p class="overview-note">Last run {_relative_time_label(run_stats["last_run"])} · {run_stats["items_added"]} stories added in the last 24 hours</p>'
            '</div>'
            f'<div class="overview-card">'
            f'<p class="overview-label">Live sources</p>'
            f'<div class="overview-value">{total_sources}</div>'
            f'<p class="overview-note">{enabled_sources} feeds · {enabled_queries} search queries</p>'
            '</div>'
            f'<div class="overview-card">'
            f'<p class="overview-label">Source health</p>'
            f'<div class="overview-value">{max(total_sources - stale_sources, 0)}</div>'
            f'<p class="overview-note">{stale_sources} stale or quiet source{"s" if stale_sources != 1 else ""}</p>'
            '</div>'
            '</section>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="empty-state">'
            '<div class="empty-state-text">No data yet — run the fetch pipeline from the Settings tab to get started.</div>'
            '<div class="empty-state-hint">Settings > Pipeline > Run Pipeline</div>'
            '</div>',
            unsafe_allow_html=True,
        )

    # Sidebar filters
    with st.sidebar:
        st.markdown(
            '<div class="sidebar-panel-heading">'
            '<div class="sidebar-panel-kicker">Control Panel</div>'
            '<div class="sidebar-panel-copy">Filter live stories, tune density, and sort by signal.</div>'
            '</div>',
            unsafe_allow_html=True,
        )

        preset_options = {
            "Last 24 hours": 1,
            "Last 7 days": 7,
            "Last 30 days": 30,
            "All time": None,
        }
        filter_preset = st.selectbox("Quick view", list(preset_options.keys()), index=2)
        preset_days = preset_options[filter_preset]

        search_query = st.text_input("Search stories", placeholder="Title, summary, source, or category")

        default_score = (8, 10) if filter_preset == "Last 24 hours" else (1, 10)
        score_range = st.slider("Score range", 1, 10, default_score)

        default_start = (
            datetime.now(timezone.utc) - timedelta(days=preset_days)
            if preset_days is not None else
            datetime.now(timezone.utc) - timedelta(days=3650)
        )
        date_range = st.date_input(
            "Date range",
            value=(default_start.date(), datetime.now(timezone.utc).date()),
        )

        show_acknowledged = st.checkbox("Show acknowledged items", value=False)

        sort_options = {"Score": "score", "Date": "published", "Source": "source", "Title": "title"}
        sort_label = st.selectbox("Sort by", list(sort_options.keys()))
        sort_dir = st.radio("Direction", ["DESC", "ASC"], horizontal=True)

        story_density = st.radio("Story density", ["Editorial", "Compact"], horizontal=True)

    # Tabs — dynamic from config categories
    categories = cfg.get("categories", ["New Releases", "Research", "Business", "Developer Tools"])
    tab_names = ["Daily Digest"] + categories + ["Settings", "About"]
    tabs = st.tabs(tab_names)

    # Prepare filter arguments
    start_date = None
    end_date = None
    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        start_date = datetime.combine(date_range[0], datetime.min.time())
        end_date = datetime.combine(date_range[1], datetime.max.time())

    filter_kwargs = dict(
        min_score=score_range[0],
        max_score=score_range[1],
        start_date=start_date,
        end_date=end_date,
        show_acknowledged=show_acknowledged,
        sort_by=sort_options[sort_label],
        sort_dir=sort_dir,
    )

    active_filters = []
    active_filters.append(filter_preset)
    if search_query:
        active_filters.append(f'Search: "{search_query}"')
    if score_range != (1, 10):
        active_filters.append(f"Score {score_range[0]}-{score_range[1]}")
    if not show_acknowledged:
        active_filters.append("Unacknowledged only")
    if sort_label != "Score" or sort_dir != "DESC":
        active_filters.append(f"{sort_label} {sort_dir}")

    st.markdown(
        '<div class="filter-chip-row">' +
        '<span class="filter-chip-label">ACTIVE FILTERS</span>' +
        "".join(f'<span class="filter-chip">{chip}</span>' for chip in active_filters) +
        f'<span class="filter-chip filter-chip-muted">{story_density} view</span>' +
        '</div>',
        unsafe_allow_html=True,
    )

    # Daily Digest tab
    with tabs[0]:
        digest_data = get_digest_items(
            cfg["db_path"],
            min_score=score_range[0],
            max_score=score_range[1],
            show_acknowledged=show_acknowledged,
            limit_days=30,
            start_date=start_date,
            end_date=end_date,
        )
        # Apply search filter
        if search_query:
            query_lower = search_query.lower()
            filtered_digest = {}
            for day, grouped_items in digest_data.items():
                filtered = []
                for primary, related in grouped_items:
                    if _matches_search(primary, query_lower):
                        filtered.append((primary, related))
                        continue
                    for item in related:
                        if _matches_search(item, query_lower):
                            filtered.append((primary, related))
                            break
                if filtered:
                    filtered_digest[day] = filtered
            digest_data = filtered_digest

        total_items = sum(
            sum(1 + len(rel) for _, rel in items)
            for items in digest_data.values()
        )
        st.markdown(
            f'<div class="section-summary">{total_items} stories across {len(digest_data)} publication days</div>',
            unsafe_allow_html=True,
        )
        _render_digest(digest_data, cfg["db_path"], cfg, compact=(story_density == "Compact"))

    # Category tabs (dynamic)
    for i, category in enumerate(categories):
        with tabs[i + 1]:
            grouped = get_grouped_items(cfg["db_path"], category, **filter_kwargs)
            grouped = filter_grouped_items(grouped, search_query)
            st.markdown(
                f'<div class="section-summary">{_count_grouped_items(grouped)} stories in {category}</div>',
                unsafe_allow_html=True,
            )
            if not grouped:
                st.markdown(
                    '<div class="empty-state">'
                    f'<div class="empty-state-text">No {category.lower()} stories matched your filters.</div>'
                    '<div class="empty-state-hint">Try widening your score range or date window</div>'
                    '</div>',
                    unsafe_allow_html=True,
                )
            else:
                _render_news_list(grouped, cfg["db_path"], cfg, compact=(story_density == "Compact"))

    # Settings tab
    with tabs[-2]:
        _render_settings_tab(cfg, db, PROJECT_ROOT)

    # About tab
    with tabs[-1]:
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
   a relevance score (1–10), a category (*New Releases*, *Research*, *Business*, or
   *Developer Tools*), a summary, score reasoning, and initial learning objectives. The
   scoring prompt is fully customizable from the Settings tab.
4. **Group** — The smart grouper clusters articles covering the same story by extracting
   significant words from titles and fuzzy-matching them. Vendor sources (OpenAI, Anthropic,
   Google, etc.) are preferred as the primary link in each group.
5. **Store** — Results are written to a local SQLite database with automatic schema migrations.

---

### Dashboard

- **Category tabs** (New Releases, Research, Business, Developer Tools) organize content by type
- **Sidebar filters** — score range, date range, sort order, and acknowledged-item visibility
- **Expandable rows** — click any row to reveal the full summary, score reasoning, learning
  objectives, metadata pills, and grouped source links
- **Acknowledge** — mark items as read; acknowledged items are hidden by default
- **Score badges** — amber for priority items, bronze for mid-signal, muted steel for lower-signal scans
- **Analyst Terminal theme** — dark graphite surfaces, mono labels, compact controls, and faster scan paths

---

### Learning Objectives with Opus

Each news item can have its learning objectives regenerated on demand using **Claude Opus**.
Click **Generate With Opus** inside any expanded row to:

- Send the item's title, source, summary, and URL to Opus with a curriculum-design prompt
- Receive 3–5 concise, actionable learning objectives (starting with action verbs)
- See a loading spinner while generating
- Once generated, see a **Generated with Opus** badge
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
| **Run Pipeline** | Execute the full fetch–score–group pipeline with live log output |
| **Scoring batch size** | Items per Claude API request (higher = fewer requests) |
| **Scoring Prompt** | The prompt sent to Sonnet for scoring — fully editable with reset |
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
| **Dashboard** | Streamlit with a dark-first Analyst Terminal theme |
| **Database** | SQLite with automatic schema migrations |
| **RSS parsing** | `feedparser` |
| **HTTP client** | `httpx` |
| **Browser scraping** | Playwright (headless Chromium) |
| **Search** | DuckDuckGo via `duckduckgo_search` |
| **Deduplication** | URL normalization + `thefuzz` (Levenshtein distance) |
| **Fuzzy grouping** | Token-sort ratio with significant-word overlap |
""")

    db.close()


if __name__ == "__main__":
    main()
