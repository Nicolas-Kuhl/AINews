#!/usr/bin/env python3
"""AI News Aggregator — Streamlit Dashboard (Rebuilt with best practices)."""

import streamlit as st
from datetime import datetime, timezone
from pathlib import Path
import yaml

from ainews.config import load_config
from ainews.dashboard.payload import build_by_day_payload, ensure_source_metas
from ainews.frontend import reader as triage_reader
from ainews.storage.database import Database
from dashboard_components import _render_settings_tab, load_css

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


@st.cache_data(ttl=60)
def _get_triage_payload(db_path: str, min_score: int, limit_days: int, cache_bust: int = 0):
    _ = cache_bust  # increments to invalidate the cache after writes
    cfg = load_config()
    db = Database(db_path)
    try:
        raw = db.query_by_day(
            min_score=min_score,
            max_score=10,
            show_acknowledged=True,
            limit_days=limit_days,
        )
        source_metas = ensure_source_metas(db, config_feeds=cfg.get("feeds"))
        day_briefs = db.get_day_briefs(list(raw.keys()))
        payload = build_by_day_payload(
            raw, source_metas=source_metas, day_briefs=day_briefs
        )
        today_key = datetime.now(timezone.utc).date().isoformat()
        morning = db.get_morning_brief(today_key)
    finally:
        db.close()
    return {"by_day": payload, "morning_brief": morning}


def _apply_triage_events(db_path: str, events: list[dict], cfg: dict) -> None:
    db = Database(db_path)
    try:
        for evt in events:
            kind = evt.get("type")
            item_id = int(evt.get("id"))
            if kind == "ack":
                if bool(evt.get("value")):
                    db.acknowledge(item_id)
                else:
                    db.unacknowledge(item_id)
            elif kind == "star":
                db.set_starred(item_id, bool(evt.get("value")))
            elif kind == "gen_lo":
                _handle_gen_lo(db, cfg, item_id)
    finally:
        db.close()


def _handle_gen_lo(db: Database, cfg: dict, item_id: int) -> None:
    """Generate learning objectives with Opus for a story and persist."""
    from dashboard_components import generate_learning_objectives

    item = db.get_by_id(item_id)
    if item is None:
        return
    try:
        objectives = generate_learning_objectives(cfg, item)
    except Exception:
        # Keep the failure silent here; the component surfaces a generic error
        # state. Full logging would require a pipeline context.
        return
    if objectives:
        db.update_learning_objectives(item_id, objectives, generated_with_opus=True)


def _render_triage_preview():
    """Phase 1 preview: render the new React triage console.

    Enable with ``?ui=reader`` in the URL. Replaces the entire dashboard body;
    the legacy UI remains the default until Phase 1 milestones land.
    """

    st.set_page_config(
        page_title="AINews",
        page_icon="📡",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    # Gate the default UI behind auth, same as the legacy and settings routes.
    # Without this, the triage console (the default) was reachable unauthenticated.
    check_authentication()
    st.markdown(
        """
        <style>
          header[data-testid="stHeader"] { display: none !important; }
          .main > div, .block-container { padding: 0 !important; max-width: 100% !important; }
          [data-testid="stAppViewContainer"] { background: #FAFAFA; }
          /* Streamlit component iframes: force full viewport height so the
             3-pane layout inside fills the screen. The title selector in
             Streamlit 1.54 is "streamlit_component.v1.iframe". */
          iframe[title^="ainews."], iframe[srcdoc], div[data-testid="stCustomComponentV1"] iframe {
            border: 0 !important;
            width: 100% !important;
            min-height: 100vh !important;
            height: 100vh !important;
          }
          .legacy-back { position: fixed; bottom: 12px; right: 14px; z-index: 9999;
                         font-family: 'Geist Mono', ui-monospace, monospace; font-size: 10px;
                         letter-spacing: 0.12em; text-transform: uppercase;
                         color: #71717A; text-decoration: none; padding: 6px 10px;
                         border: 1px solid #E4E4E7; border-radius: 6px;
                         background: rgba(255,255,255,0.9); }
          .legacy-back:hover { color: #0A0A0A; border-color: #D4D4D8; }
        </style>
        <a class="legacy-back" href="?ui=legacy" target="_self">Legacy UI</a>
        """,
        unsafe_allow_html=True,
    )
    cfg = load_config()
    cache_bust = st.session_state.get("triage_cache_bust", 0)
    bundle = _get_triage_payload(
        cfg["db_path"], min_score=1, limit_days=30, cache_bust=cache_bust
    )
    result = triage_reader(
        by_day=bundle["by_day"],
        morning_brief=bundle["morning_brief"],
        theme_default="paper",
        key="ainews_reader_preview",
    )
    if isinstance(result, dict):
        seq = result.get("seq")
        last_seq = st.session_state.get("triage_last_seq")
        if seq is not None and seq != last_seq:
            st.session_state["triage_last_seq"] = seq
            events = result.get("events") or []
            if events:
                _apply_triage_events(cfg["db_path"], events, cfg)
                st.session_state["triage_cache_bust"] = cache_bust + 1
                st.rerun()


def _render_settings_standalone():
    """Render the existing Settings tab as a dedicated page (for the new UI).

    Reached via ``?settings=1``. Keeps the existing auth + CSS chrome so the
    experience matches the legacy dashboard, with a small "Back to dashboard"
    link that returns to the triage console.
    """

    st.set_page_config(page_title="AINews · Settings", page_icon="📡", layout="wide")
    check_authentication()
    load_css(PROJECT_ROOT / "assets" / "style.css")
    st.markdown(
        """
        <style>
          .settings-back { display: inline-flex; align-items: center; gap: 6px;
                           font-family: 'Geist Mono', ui-monospace, monospace;
                           font-size: 11px; letter-spacing: 0.12em;
                           text-transform: uppercase; color: #71717A;
                           text-decoration: none; margin-bottom: 16px; }
          .settings-back:hover { color: #0A0A0A; }
        </style>
        <a class="settings-back" href="/" target="_self">← Back to dashboard</a>
        """,
        unsafe_allow_html=True,
    )
    cfg = load_config()
    db = Database(cfg["db_path"])
    try:
        _render_settings_tab(cfg, db, PROJECT_ROOT)
    finally:
        db.close()


def main():
    # Routes: the standalone Settings page, or the React triage console
    # (the only UI). The legacy Streamlit dashboard has been retired.
    if st.query_params.get("settings") == "1":
        _render_settings_standalone()
        return
    _render_triage_preview()


if __name__ == "__main__":
    main()
