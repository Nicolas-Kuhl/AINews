#!/usr/bin/env python3
"""AI News Aggregator — Streamlit Dashboard (Rebuilt with best practices)."""

import streamlit as st
from datetime import datetime, timedelta
from pathlib import Path
import yaml

from ainews.config import load_config
from ainews.storage.database import Database
from dashboard_components import _render_news_list, _render_settings_tab, load_css

PROJECT_ROOT = Path(__file__).resolve().parent


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
    st.set_page_config(page_title="AI News Aggregator", page_icon="📡", layout="wide")

    # Check authentication
    check_authentication()

    # Load CSS from external file
    load_css(PROJECT_ROOT / "assets" / "style.css")

    st.title("AI News Aggregator")

    cfg = load_config()
    db = Database(cfg["db_path"])

    # Run status bar
    run_stats = db.get_last_run_stats()
    if run_stats:
        st.markdown(
            f"**Last run:** {run_stats['last_run']} · **Items added:** {run_stats['items_added']}"
        )
    else:
        st.info("No data yet — run the fetch pipeline to get started.")

    # Sidebar filters
    with st.sidebar:
        st.header("Filters")

        score_range = st.slider("Score range", 1, 10, (1, 10))

        default_start = datetime.utcnow() - timedelta(days=30)
        date_range = st.date_input(
            "Date range",
            value=(default_start.date(), datetime.utcnow().date()),
        )

        show_acknowledged = st.checkbox("Show acknowledged items", value=False)

        sort_options = {"Score": "score", "Date": "published", "Source": "source", "Title": "title"}
        sort_label = st.selectbox("Sort by", list(sort_options.keys()))
        sort_dir = st.radio("Direction", ["DESC", "ASC"], horizontal=True)

    # Tabs
    tab_releases, tab_industry, tab_settings, tab_about = st.tabs(
        ["New Releases", "Industry News", "Settings", "About"]
    )

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

    # New Releases tab
    with tab_releases:
        grouped = db.query_grouped(category="New Releases", **filter_kwargs)
        st.subheader(f"New Releases ({len(grouped)})")
        if not grouped:
            st.info("📡 No new release items found matching your filters.")
        else:
            _render_news_list(grouped, db, cfg)

    # Industry tab
    with tab_industry:
        grouped = db.query_grouped(category="Industry", **filter_kwargs)
        st.subheader(f"Industry News ({len(grouped)})")
        if not grouped:
            st.info("📰 No industry items found matching your filters.")
        else:
            _render_news_list(grouped, db, cfg)

    # Settings tab
    with tab_settings:
        _render_settings_tab(cfg, db, PROJECT_ROOT)

    # About tab
    with tab_about:
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
   a relevance score (1–10), a category (*New Releases* or *Industry*), a summary, score
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
- **Score badges** — color-coded (red ≥ 8, orange ≥ 5, muted below)
- **Native Streamlit components** for smooth, accessible interface

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
| **Dashboard** | Streamlit with custom Pluralsight-inspired dark theme |
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
