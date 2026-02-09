"""Dashboard rendering components for AI News Aggregator."""

import subprocess
import sys
from pathlib import Path

import anthropic
import streamlit as st
from ddgs import DDGS

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


def load_css(css_file_path: Path):
    """Load external CSS file."""
    if css_file_path.exists():
        with open(css_file_path, 'r', encoding='utf-8') as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


def _search_web_for_context(query: str, max_results: int = 3) -> str:
    """Search the web and return formatted context for Claude."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))

        if not results:
            return "No search results found."

        context_parts = []
        for i, result in enumerate(results, 1):
            title = result.get('title', 'No title')
            body = result.get('body', 'No description')
            url = result.get('href', '')
            context_parts.append(f"{i}. **{title}**\n   {body}\n   Source: {url}")

        return "\n\n".join(context_parts)
    except Exception as e:
        return f"Search error: {e}"


def _web_search_tool(query: str) -> str:
    """Web search tool for Claude to use via tool calling."""
    return _search_web_for_context(query, max_results=3)


def generate_learning_objectives(cfg: dict, item):
    """Call Claude Opus with extended thinking and web research to generate learning objectives."""
    api_key = cfg.get("anthropic_api_key", "")
    prompt_template = cfg.get("lo_prompt") or DEFAULT_LO_PROMPT

    # Build base prompt
    base_prompt = prompt_template.format(
        title=item.title,
        source=item.source,
        summary=item.summary or "(no summary available)",
        url=item.url,
    )

    # Option 3: Pre-fetch web search results if enabled
    web_research_enabled = cfg.get("lo_web_research", False)
    search_context = ""

    if web_research_enabled:
        search_count = cfg.get("lo_search_count", 3)
        search_query = f"{item.title} AI news"

        try:
            search_results = _search_web_for_context(search_query, max_results=search_count)
            search_context = f"\n\n---\n**Additional Web Research:**\n{search_results}\n---\n"
        except Exception as e:
            search_context = f"\n\n(Web research unavailable: {e})\n"

    # Combine prompt with search context
    full_prompt = base_prompt + search_context

    # Option 2: Define web search tool for Claude to use
    tools = [
        {
            "name": "web_search",
            "description": "Search the web for current information about a topic. Use this to find additional context, technical details, or recent developments that aren't in your training data.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to run"
                    }
                },
                "required": ["query"]
            }
        }
    ]

    client = anthropic.Anthropic(api_key=api_key)
    lo_model = cfg.get("lo_model", "claude-opus-4-6")

    # Initial request with tools
    messages = [{"role": "user", "content": full_prompt}]

    response = client.messages.create(
        model=lo_model,
        max_tokens=4096,
        thinking={
            "type": "enabled",
            "budget_tokens": 3000
        },
        tools=tools if web_research_enabled else None,
        messages=messages,
    )

    # Handle tool use (if Claude wants to search)
    while response.stop_reason == "tool_use":
        tool_uses = [block for block in response.content if block.type == "tool_use"]

        # Execute tools
        tool_results = []
        for tool_use in tool_uses:
            if tool_use.name == "web_search":
                query = tool_use.input["query"]
                result = _web_search_tool(query)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result
                })

        # Add assistant response and tool results to messages
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

        # Continue conversation
        response = client.messages.create(
            model=lo_model,
            max_tokens=4096,
            tools=tools if web_research_enabled else None,
            messages=messages,
        )

    # Extract text content (skip thinking blocks)
    text_content = ""
    for block in response.content:
        if block.type == "text":
            text_content += block.text

    return text_content.strip()


def _render_news_list(grouped_items, db, cfg):
    """Render list of grouped news items as a compact table."""
    # Table header (using container without HTML div wrapper)
    with st.container():
        h_cols = st.columns([0.5, 0.6, 5.3, 1.8, 1.2, 0.9])
        h_cols[0].markdown("")  # Expand arrow column (wider for spacing)
        h_cols[1].markdown("**Score**")
        h_cols[2].markdown("**Title**")
        h_cols[3].markdown("**Source**")
        h_cols[4].markdown("**Date**")
        h_cols[5].markdown("**Action**")

    # Render each news item
    for primary, related in grouped_items:
        _render_news_item(primary, related, db, cfg)


def _render_news_item(primary, related, db, cfg):
    """Render a single news item as a table row with expandable details."""
    # Check if expanded
    expand_key = f"expand_{primary.id}"
    is_expanded = st.session_state.get(expand_key, False)

    # Handle acknowledge: process immediately without blocking animation
    ack_pending_key = f"ack_pending_{primary.id}"
    if st.session_state.get(ack_pending_key, False):
        db.acknowledge(primary.id)
        for rel in related:
            if rel.id:
                db.acknowledge(rel.id)
        st.session_state.pop(ack_pending_key, None)
        return

    # Main row
    with st.container():
        cols = st.columns([0.5, 0.6, 5.3, 1.8, 1.2, 0.9])

        # Expand/collapse button (first column)
        with cols[0]:
            arrow = "▾" if is_expanded else "▸"
            if st.button(arrow, key=f"toggle_{primary.id}"):
                st.session_state[expand_key] = not is_expanded
                st.rerun()

        # Score pill with color coding
        if primary.score >= 8:
            pill_color = "#d32f2f"
        elif primary.score >= 5:
            pill_color = "#f39c12"
        else:
            pill_color = "#6b7280"

        cols[1].markdown(
            f'<span style="background-color:{pill_color};color:#ffffff;padding:0.25rem 0.65rem;'
            f'border-radius:12px;font-weight:700;font-size:0.85rem;display:inline-block;'
            f'text-align:center;min-width:2rem;">{primary.score}</span>',
            unsafe_allow_html=True
        )

        # Title as clickable link with related count
        title_text = f"[{primary.title}]({primary.url})"
        if related:
            title_text += f" `+{len(related)}`"
        cols[2].markdown(title_text)

        # Source
        cols[3].caption(primary.source)

        # Date (with time)
        if primary.published:
            date_str = primary.published.strftime("%b %d %H:%M")
        else:
            date_str = "—"
        cols[4].caption(date_str)

        # Acknowledge button
        with cols[5]:
            if not primary.acknowledged:
                if st.button("Ack", key=f"ack_{primary.id}", type="primary"):
                    st.session_state[ack_pending_key] = True
                    st.cache_data.clear()
                    st.rerun()
            else:
                st.markdown("✅")

    # Expandable details (only shown when expanded)
    if is_expanded:
        _render_item_details(primary, related, db, cfg)


def _render_item_details(primary, related, db, cfg):
    """Render detailed content inside expander."""
    # Summary
    if primary.summary:
        st.markdown('<span class="section-pill">Summary</span>', unsafe_allow_html=True)
        st.markdown(primary.summary)
        st.markdown("")

    # Score reasoning
    if primary.score_reasoning:
        st.markdown('<span class="section-pill">Score Reasoning</span>', unsafe_allow_html=True)
        st.markdown(primary.score_reasoning)
        st.markdown("")

    # Learning objectives
    st.markdown('<span class="section-pill">Learning Objectives</span>', unsafe_allow_html=True)
    _render_learning_objectives(primary, cfg, db)

    # Metadata (no heading)
    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    col1.caption(f"**Category:** {primary.category}")
    col2.caption(f"**Fetched via:** {primary.fetched_via}")
    if primary.published:
        # Format as "YYYY-MM-DD HH:MM" in UTC
        date_str = primary.published.strftime('%Y-%m-%d %H:%M')
        col3.caption(f"**Published:** {date_str} UTC")

    # Related sources
    if related:
        st.markdown("---")
        st.markdown(f"### All Sources ({len([primary] + related)} total)")
        for idx, item in enumerate([primary] + related, 1):
            # Format date as "Mon DD HH:MM" in UTC
            date_str = item.published.strftime("%b %d %H:%M") if item.published else "—"

            # Score pill color
            if item.score >= 8:
                score_badge = f'<span style="background-color:#d32f2f;color:#fff;padding:0.1rem 0.4rem;border-radius:6px;font-size:0.7rem;font-weight:700;">{item.score}</span>'
            elif item.score >= 5:
                score_badge = f'<span style="background-color:#f39c12;color:#fff;padding:0.1rem 0.4rem;border-radius:6px;font-size:0.7rem;font-weight:700;">{item.score}</span>'
            else:
                score_badge = f'<span style="background-color:#6b7280;color:#fff;padding:0.1rem 0.4rem;border-radius:6px;font-size:0.7rem;font-weight:700;">{item.score}</span>'

            st.markdown(
                f"{idx}. [{item.title}]({item.url}) · **{item.source}** · {date_str} · {score_badge}",
                unsafe_allow_html=True
            )


def _render_learning_objectives(primary, cfg, db):
    """Render learning objectives section with generate button."""
    lo_gen_key = f"gen_lo_{primary.id}"
    lo_err_key = f"gen_lo_err_{primary.id}"
    is_generating = st.session_state.get(lo_gen_key, False)

    # Show badge if generated with Opus
    if primary.lo_generated_with_opus and not is_generating:
        st.markdown(
            '<span class="opus-badge">&#9679; Generated with Claude Opus 4.6</span>',
            unsafe_allow_html=True,
        )
        st.markdown("")

    # Generate button
    if not is_generating and not primary.lo_generated_with_opus:
        if st.button("Generate with Opus", key=f"gen_btn_{primary.id}", type="primary"):
            st.session_state[lo_gen_key] = True
            st.rerun()

    # Show error if any
    prev_err = st.session_state.get(lo_err_key)
    if prev_err:
        st.error(prev_err)

    # Generate or display
    if is_generating:
        with st.spinner("Generating learning objectives with Claude Opus..."):
            try:
                new_lo = generate_learning_objectives(cfg, primary)
                db.update_learning_objectives(primary.id, new_lo, generated_with_opus=True)
                primary.learning_objectives = new_lo
                primary.lo_generated_with_opus = True
                # Clear cache so updated data shows immediately
                st.cache_data.clear()
            except Exception as e:
                st.session_state[lo_err_key] = f"Generation failed: {e}"
        st.session_state[lo_gen_key] = False
        st.rerun()
    else:
        if primary.learning_objectives:
            st.markdown(primary.learning_objectives)
        else:
            st.info("Click **Generate with Opus** to create tailored learning objectives for this news item.")


def _render_settings_tab(cfg, db, project_root):
    """Render the Settings tab."""
    # RSS Feed Generator
    st.subheader("RSS Feed")
    st.caption("Generate an RSS feed of high-priority news items (score 8+) for your RSS reader.")

    rss_col1, rss_col2 = st.columns([3, 1])
    with rss_col1:
        min_rss_score = st.slider(
            "Minimum score for RSS feed",
            min_value=1,
            max_value=10,
            value=8,
            help="Only items with this score or higher will be included in the RSS feed"
        )

    with rss_col2:
        if st.button("Generate RSS", key="generate_rss", type="primary"):
            from ainews.rss_generator import generate_rss_feed

            # Query items for RSS feed
            items = db.query_items(
                min_score=min_rss_score,
                show_acknowledged=False,
                sort_by="published",
                sort_dir="DESC"
            )

            # Generate RSS XML
            rss_xml = generate_rss_feed(items, min_score=min_rss_score)

            # Store in session state for download
            st.session_state['rss_feed_xml'] = rss_xml
            st.session_state['rss_item_count'] = len([item for item in items if item.score >= min_rss_score])

    # Show download button if RSS was generated
    if 'rss_feed_xml' in st.session_state:
        item_count = st.session_state.get('rss_item_count', 0)
        st.success(f"RSS feed generated with {item_count} items!")
        st.download_button(
            label="Download RSS Feed",
            data=st.session_state['rss_feed_xml'],
            file_name=f"ainews_score{min_rss_score}plus.xml",
            mime="application/rss+xml",
            key="download_rss"
        )
        st.caption("💡 Save this file and add it to your RSS reader, or host it on a web server for automatic updates.")

    st.divider()

    # Pipeline Runner
    st.subheader("Fetch Pipeline")
    st.caption("Run the full pipeline: fetch RSS & search, deduplicate, score with Claude, group, and generate RSS feed.")

    log_file = project_root / "data" / "pipeline.log"
    if st.button("Run Pipeline", key="run_pipeline", type="primary"):
        with st.status("Running pipeline...", expanded=True) as status:
            log_area = st.empty()
            log_text = ""
            process = subprocess.Popen(
                [sys.executable, "-u", str(project_root / "fetch_news.py")],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(project_root),
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

    # Pipeline Log
    if log_file.exists():
        with st.expander("Pipeline Log", expanded=False):
            st.code(log_file.read_text())

    st.divider()

    # Scoring Settings
    st.subheader("Scoring Settings")
    from ainews.config import save_config

    new_batch_size = st.number_input(
        "Scoring batch size",
        min_value=1,
        max_value=50,
        value=cfg.get("scoring_batch_size", 10),
        help="Number of items sent to Claude per API request. Higher = fewer requests but larger prompts.",
    )
    if new_batch_size != cfg.get("scoring_batch_size", 10):
        cfg["scoring_batch_size"] = int(new_batch_size)
        save_config(cfg)

    # Scoring Prompt
    from ainews.processing.scorer import DEFAULT_SCORING_PROMPT

    current_prompt = cfg.get("scoring_prompt") or DEFAULT_SCORING_PROMPT
    with st.expander("Scoring Prompt", expanded=False):
        st.caption("The prompt sent to Claude for each batch. Use {items_text} as the placeholder for news items.")
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

    # Learning Objectives Prompt
    current_lo_prompt = cfg.get("lo_prompt") or DEFAULT_LO_PROMPT
    with st.expander("Learning Objectives Prompt (Opus)", expanded=False):
        st.caption(
            "The prompt sent to Claude Opus when generating learning objectives. "
            "Available placeholders: {title}, {source}, {summary}, {url}."
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

    # Smart Grouper
    st.subheader("Smart Grouper")
    st.caption("Re-analyze all items and group related news coverage together.")
    if st.button("Run Smart Grouper", key="run_grouper", type="primary"):
        from ainews.processing.grouper import run_grouper

        with st.spinner("Grouping items..."):
            count = run_grouper(db)
        st.success(f"Done — created {count} groups.")
        st.rerun()

    st.divider()

    # Sources Management
    feeds = cfg.get("feeds", [])
    rss_feeds = [(i, f) for i, f in enumerate(feeds) if f.get("type", "auto") in ("rss", "auto")]
    web_feeds = [(i, f) for i, f in enumerate(feeds) if f.get("type") == "web"]

    # RSS & Auto-Detect Feeds
    st.subheader("RSS & Auto-Detect Feeds")
    st.caption("Fetched via feedparser (rss) or httpx with auto-detection (auto). These use standard HTTP requests.")

    for idx, feed in rss_feeds:
        feed_type = feed.get("type", "auto")
        is_enabled = feed.get("enabled", True)
        col_toggle, col_type, col_name, col_url, col_rm = st.columns([0.4, 0.8, 2.5, 5, 0.4])

        with col_toggle:
            enabled = st.toggle(
                "on",
                value=is_enabled,
                key=f"toggle_rss_{idx}",
                label_visibility="collapsed",
            )
            if enabled != is_enabled:
                cfg["feeds"][idx]["enabled"] = enabled
                save_config(cfg)
                st.rerun()

        col_type.markdown(f"`{feed_type}`")
        name_style = "font-weight:500;" if is_enabled else "font-weight:500;color:#555;"
        col_name.markdown(f'<span style="{name_style}">{feed["name"]}</span>', unsafe_allow_html=True)
        url_style = "font-size:0.8rem;" if is_enabled else "font-size:0.8rem;color:#444;"
        col_url.caption(feed["url"])

        with col_rm:
            if st.button("✕", key=f"rm_feed_{idx}"):
                cfg["feeds"].pop(idx)
                save_config(cfg)
                st.rerun()

    # Add RSS/Auto Feed
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

    # Website Feeds (Browser Scraping)
    st.subheader("Websites (Browser Scraping)")
    st.caption("Fetched via headless browser (Playwright) for JS-rendered pages that block simple HTTP requests.")

    for idx, feed in web_feeds:
        is_enabled = feed.get("enabled", True)
        col_toggle, col_name, col_url, col_rm = st.columns([0.4, 3, 5.2, 0.4])

        with col_toggle:
            enabled = st.toggle(
                "on",
                value=is_enabled,
                key=f"toggle_web_{idx}",
                label_visibility="collapsed",
            )
            if enabled != is_enabled:
                cfg["feeds"][idx]["enabled"] = enabled
                save_config(cfg)
                st.rerun()

        name_style = "font-weight:500;" if is_enabled else "font-weight:500;color:#555;"
        col_name.markdown(f'<span style="{name_style}">{feed["name"]}</span>', unsafe_allow_html=True)
        col_url.caption(feed["url"])

        with col_rm:
            if st.button("✕", key=f"rm_feed_{idx}"):
                cfg["feeds"].pop(idx)
                save_config(cfg)
                st.rerun()

    # Add Website
    with st.container():
        st.markdown("**Add Website**")
        aw1, aw2, aw3 = st.columns([3, 5.5, 1])
        new_web_name = aw1.text_input("Name", key="new_web_name", label_visibility="collapsed", placeholder="Site name")
        new_web_url = aw2.text_input("URL", key="new_web_url", label_visibility="collapsed", placeholder="https://example.com/news/")
        with aw3:
            if st.button("Add", key="add_web_feed", type="primary"):
                if new_web_name and new_web_url:
                    cfg.setdefault("feeds", []).append({
                        "name": new_web_name,
                        "url": new_web_url,
                        "type": "web",
                        "enabled": True
                    })
                    save_config(cfg)
                    st.rerun()

    st.divider()

    # Search Queries Management
    st.subheader("Search Queries")
    queries = cfg.get("search_queries", [])
    for i, q in enumerate(queries):
        col_q, col_rm = st.columns([9, 1])
        col_q.markdown(f"**{q}**")
        with col_rm:
            if st.button("✕", key=f"rm_query_{i}", type="primary"):
                cfg["search_queries"].pop(i)
                save_config(cfg)
                st.rerun()

    # Add Search Query
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

    # Source Scan History
    st.subheader("Source Scan History")
    source_status = db.get_source_status()
    if not source_status:
        st.info("No scan data yet. Run the fetch pipeline to populate.")
    else:
        # Use native table
        for s in source_status:
            col_src, col_count, col_last = st.columns([4, 2, 4])
            col_src.markdown(f"**{s['source']}**")
            col_count.markdown(f"{s['item_count']}")
            col_last.caption(s["last_scanned"])
