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
    """Load external CSS file and font links."""
    # Font links — must be <link> tags, NOT @import inside <style>
    st.markdown(
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">',
        unsafe_allow_html=True,
    )
    if css_file_path.exists():
        with open(css_file_path, 'r', encoding='utf-8') as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


def _search_web_for_context(query: str, max_results: int = 3) -> str:
    """Search the web and return formatted context for Claude."""
    try:
        with DDGS(verify=False) as ddgs:
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


@st.fragment
def _render_news_list(grouped_items, db_path, cfg):
    """Render list of grouped news items as a compact table.

    Decorated with @st.fragment so that expand/collapse and acknowledge
    clicks only rerun this fragment, not the entire page.

    Accepts db_path (not a Database object) because fragments can rerun
    after main() has closed its connection.  A fresh connection is opened
    here so writes (acknowledge, update LO) always work.
    """
    from ainews.storage.database import Database

    db = Database(db_path)

    # Table header
    with st.container():
        h_cols = st.columns([0.4, 0.5, 5.5, 1.8, 1.2, 0.8])
        h_cols[0].markdown("")
        h_cols[1].markdown('<span class="date-mono" style="font-size:0.65rem;letter-spacing:0.06em;opacity:0.5;">SCORE</span>', unsafe_allow_html=True)
        h_cols[2].markdown('<span class="date-mono" style="font-size:0.65rem;letter-spacing:0.06em;opacity:0.5;">TITLE</span>', unsafe_allow_html=True)
        h_cols[3].markdown('<span class="date-mono" style="font-size:0.65rem;letter-spacing:0.06em;opacity:0.5;">SOURCE</span>', unsafe_allow_html=True)
        h_cols[4].markdown('<span class="date-mono" style="font-size:0.65rem;letter-spacing:0.06em;opacity:0.5;">DATE</span>', unsafe_allow_html=True)
        h_cols[5].markdown("")

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
        cols = st.columns([0.4, 0.5, 5.5, 1.8, 1.2, 0.8])

        # Expand/collapse button
        with cols[0]:
            arrow = "▾" if is_expanded else "▸"
            if st.button(arrow, key=f"toggle_{primary.id}"):
                st.session_state[expand_key] = not is_expanded
                st.rerun(scope="fragment")

        # Score — colored number only
        if primary.score >= 8:
            score_class = "high"
        elif primary.score >= 5:
            score_class = "mid"
        else:
            score_class = "low"

        cols[1].markdown(
            f'<span class="score-num {score_class}">{primary.score}</span>',
            unsafe_allow_html=True
        )

        # Title as clickable link with related count badge
        title_md = f"[{primary.title}]({primary.url})"
        if related:
            title_md += f' <span class="related-count">+{len(related)}</span>'
        cols[2].markdown(title_md, unsafe_allow_html=True)

        # Source
        cols[3].caption(primary.source)

        # Date (monospace for alignment)
        if primary.published:
            date_str = primary.published.strftime("%b %d %H:%M")
        else:
            date_str = "—"
        cols[4].markdown(
            f'<span class="date-mono">{date_str}</span>',
            unsafe_allow_html=True
        )

        # Acknowledge button
        with cols[5]:
            if not primary.acknowledged:
                if st.button("✓", key=f"ack_{primary.id}"):
                    st.session_state[ack_pending_key] = True
                    st.cache_data.clear()
                    st.rerun(scope="fragment")
            else:
                st.markdown('<span style="color:var(--text-muted);font-size:0.8rem;">✓</span>', unsafe_allow_html=True)

    # Expandable details — indented to align under title column
    if is_expanded:
        _, detail_col = st.columns([0.9, 9.3])
        with detail_col:
            _render_item_details(primary, related, db, cfg)


def _render_item_details(primary, related, db, cfg):
    """Render detailed content inside expander."""
    # Summary
    if primary.summary:
        st.markdown('<span class="section-label">Summary</span>', unsafe_allow_html=True)
        st.markdown(primary.summary)

    # Score reasoning
    if primary.score_reasoning:
        st.markdown('<span class="section-label">Score Reasoning</span>', unsafe_allow_html=True)
        st.markdown(primary.score_reasoning)

    # Learning objectives
    st.markdown('<span class="section-label">Learning Objectives</span>', unsafe_allow_html=True)
    _render_learning_objectives(primary, cfg, db)

    # All sources (when grouped) — harmonised score badges
    if related:
        all_items = [primary] + related
        st.markdown(f'<span class="section-label">All Sources ({len(all_items)})</span>', unsafe_allow_html=True)
        for idx, item in enumerate(all_items, 1):
            date_str = item.published.strftime("%b %d %H:%M") if item.published else "—"

            if item.score >= 8:
                score_class = "high"
            elif item.score >= 5:
                score_class = "mid"
            else:
                score_class = "low"
            score_badge = f'<span class="score-num-sm {score_class}">{item.score}</span>'

            st.markdown(
                f'{idx}. [{item.title}]({item.url}) · **{item.source}** · '
                f'<span class="date-mono">{date_str}</span> · {score_badge}',
                unsafe_allow_html=True
            )

    # Metadata footer
    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    col1.caption(f"**Category:** {primary.category}")
    col2.caption(f"**Fetched via:** {primary.fetched_via}")
    if primary.published:
        date_str = primary.published.strftime('%Y-%m-%d %H:%M')
        col3.markdown(
            f'<span style="font-size:0.75rem;color:var(--text-muted);">'
            f'<strong>Published:</strong> <span class="date-mono">{date_str} UTC</span></span>',
            unsafe_allow_html=True
        )

    # Article content (collapsible, at the bottom)
    if primary.content:
        with st.expander("Full Article Content", expanded=False):
            st.markdown(primary.content)


def _render_learning_objectives(primary, cfg, db):
    """Render learning objectives section with generate button."""
    lo_gen_key = f"gen_lo_{primary.id}"
    lo_err_key = f"gen_lo_err_{primary.id}"
    is_generating = st.session_state.get(lo_gen_key, False)

    # Show badge if generated with Opus
    if primary.lo_generated_with_opus and not is_generating:
        st.markdown(
            '<span class="opus-badge">Generated with Opus</span>',
            unsafe_allow_html=True,
        )

    # Generate button
    if not is_generating and not primary.lo_generated_with_opus:
        if st.button("Generate with Opus", key=f"gen_btn_{primary.id}", type="primary"):
            st.session_state[lo_gen_key] = True
            st.rerun(scope="fragment")

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
        st.rerun(scope="fragment")
    else:
        if primary.learning_objectives:
            st.markdown(primary.learning_objectives)
        else:
            st.info("Click **Generate with Opus** to create tailored learning objectives for this news item.")


def _render_settings_tab(cfg, db, project_root):
    """Render the Settings tab with grouped sections."""
    from ainews.config import save_config

    # ── Pipeline ──
    with st.expander("Pipeline", expanded=True):
        st.markdown("**RSS Feed**")
        st.caption("Generate an RSS feed of high-priority news items.")

        rss_col1, rss_col2 = st.columns([3, 1])
        with rss_col1:
            min_rss_score = st.number_input(
                "Minimum score for RSS feed",
                min_value=1, max_value=10,
                value=cfg.get("rss_min_score", 8),
                help="Only items with this score or higher will be included in the RSS feed"
            )
        with rss_col2:
            st.markdown("")
            if st.button("Generate RSS", key="generate_rss", type="primary"):
                from ainews.rss_generator import generate_rss_feed
                items = db.query_items(
                    min_score=min_rss_score, show_acknowledged=False,
                    sort_by="published", sort_dir="DESC"
                )
                rss_xml = generate_rss_feed(items, min_score=min_rss_score)
                st.session_state['rss_feed_xml'] = rss_xml
                st.session_state['rss_item_count'] = len([item for item in items if item.score >= min_rss_score])

        if 'rss_feed_xml' in st.session_state:
            item_count = st.session_state.get('rss_item_count', 0)
            st.success(f"RSS feed generated with {item_count} items!")
            st.download_button(
                label="Download RSS Feed",
                data=st.session_state['rss_feed_xml'],
                file_name=f"ainews_score{min_rss_score}plus.xml",
                mime="application/rss+xml", key="download_rss"
            )

        st.divider()

        st.markdown("**Fetch Pipeline**")
        st.caption("Run the full pipeline: fetch, deduplicate, score, group.")

        log_file = project_root / "data" / "pipeline.log"
        if st.button("Run Pipeline", key="run_pipeline", type="primary"):
            with st.status("Running pipeline...", expanded=True) as status:
                log_area = st.empty()
                log_text = ""
                process = subprocess.Popen(
                    [sys.executable, "-u", str(project_root / "fetch_news.py")],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, cwd=str(project_root),
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

    # ── Scoring & Prompts ──
    with st.expander("Scoring & Prompts", expanded=False):
        st.markdown("**Scoring Settings**")
        new_batch_size = st.number_input(
            "Scoring batch size", min_value=1, max_value=50,
            value=cfg.get("scoring_batch_size", 10),
            help="Number of items sent to Claude per API request.",
        )
        if new_batch_size != cfg.get("scoring_batch_size", 10):
            cfg["scoring_batch_size"] = int(new_batch_size)
            save_config(cfg)

        st.divider()

        from ainews.processing.scorer import DEFAULT_SCORING_PROMPT
        current_prompt = cfg.get("scoring_prompt") or DEFAULT_SCORING_PROMPT
        with st.expander("Scoring Prompt", expanded=False):
            st.caption("Use {items_text} as the placeholder for news items.")
            edited_prompt = st.text_area(
                "Scoring prompt", value=current_prompt, height=400,
                label_visibility="collapsed", key="scoring_prompt_editor",
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

        current_lo_prompt = cfg.get("lo_prompt") or DEFAULT_LO_PROMPT
        with st.expander("Learning Objectives Prompt (Opus)", expanded=False):
            st.caption("Placeholders: {title}, {source}, {summary}, {url}.")
            edited_lo_prompt = st.text_area(
                "LO prompt", value=current_lo_prompt, height=350,
                label_visibility="collapsed", key="lo_prompt_editor",
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

        st.markdown("**Deduplication**")
        st.caption("Control how the pipeline detects and removes duplicate news items.")
        dedup_col1, dedup_col2 = st.columns(2)
        with dedup_col1:
            new_dedup_threshold = st.number_input(
                "Fuzzy match threshold", min_value=1, max_value=100,
                value=cfg.get("dedup_threshold", 80),
                help="Items with title similarity above this threshold are auto-removed as duplicates.",
                key="dedup_threshold_input",
            )
            if new_dedup_threshold != cfg.get("dedup_threshold", 80):
                cfg["dedup_threshold"] = int(new_dedup_threshold)
                save_config(cfg)
        with dedup_col2:
            new_borderline_low = st.number_input(
                "Borderline match threshold", min_value=1, max_value=100,
                value=cfg.get("borderline_threshold", 50),
                help="Items between this and fuzzy threshold are sent to Claude for semantic review.",
                key="borderline_threshold_input",
            )
            if new_borderline_low != cfg.get("borderline_threshold", 50):
                cfg["borderline_threshold"] = int(new_borderline_low)
                save_config(cfg)

        semantic_enabled = st.toggle(
            "Enable semantic dedup (Claude)",
            value=cfg.get("semantic_dedup", True),
            help="Use Claude Sonnet to judge borderline title matches.",
            key="semantic_dedup_toggle",
        )
        if semantic_enabled != cfg.get("semantic_dedup", True):
            cfg["semantic_dedup"] = semantic_enabled
            save_config(cfg)

        st.divider()

        st.markdown("**Content Fetching**")
        st.caption("Fetch full article text to improve scoring accuracy.")
        content_enabled = st.toggle(
            "Enable content fetching",
            value=cfg.get("content_fetching", True),
            help="Full article text is fetched after dedup and included in Claude's scoring context.",
            key="content_fetching_toggle",
        )
        if content_enabled != cfg.get("content_fetching", True):
            cfg["content_fetching"] = content_enabled
            save_config(cfg)

        cf_col1, cf_col2 = st.columns(2)
        with cf_col1:
            new_max_store = st.number_input(
                "Max content stored (chars)", min_value=1000, max_value=50000,
                value=cfg.get("content_max_chars", 10000),
                key="content_max_chars_input",
            )
            if new_max_store != cfg.get("content_max_chars", 10000):
                cfg["content_max_chars"] = int(new_max_store)
                save_config(cfg)
        with cf_col2:
            new_max_score = st.number_input(
                "Max content for scoring (chars)", min_value=500, max_value=10000,
                value=cfg.get("content_score_chars", 3000),
                key="content_score_chars_input",
            )
            if new_max_score != cfg.get("content_score_chars", 3000):
                cfg["content_score_chars"] = int(new_max_score)
                save_config(cfg)

    # ── Maintenance ──
    with st.expander("Maintenance", expanded=False):
        st.markdown("**Smart Grouper**")
        st.caption("Re-analyze all items and group related news coverage together.")
        grouper_col1, grouper_col2 = st.columns(2)
        with grouper_col1:
            if st.button("Run Smart Grouper", key="run_grouper", type="primary"):
                from ainews.processing.grouper import run_grouper
                with st.spinner("Grouping items..."):
                    count = run_grouper(db)
                st.success(f"Done — created {count} groups.")
                st.rerun()
        with grouper_col2:
            if st.button("Deep Semantic Dedup", key="run_deep_dedup"):
                from ainews.processing.grouper import deep_semantic_dedup
                api_key = cfg.get("anthropic_api_key", "")
                if not api_key:
                    st.error("No Anthropic API key configured.")
                else:
                    client = anthropic.Anthropic(api_key=api_key)
                    model = cfg.get("model", "claude-sonnet-4-5-20250929")
                    with st.spinner("Scanning unacknowledged items for semantic duplicates with Claude..."):
                        count = deep_semantic_dedup(db, client, model)
                    if count > 0:
                        st.success(f"Found and grouped {count} duplicate pair{'s' if count != 1 else ''}.")
                    else:
                        st.info("No additional duplicates found.")
                    st.cache_data.clear()
                    st.rerun()

        st.divider()

        st.markdown("**Bulk Acknowledge**")
        col_date, col_score = st.columns(2)
        with col_date:
            st.caption("Acknowledge all items before a date.")
            ack_date = st.date_input("Acknowledge items older than", key="bulk_ack_date")
            if st.button("Acknowledge Before Date", key="bulk_ack_btn", type="primary"):
                from datetime import datetime, time
                cutoff = datetime.combine(ack_date, time.min)
                count = db.acknowledge_before_date(cutoff)
                st.cache_data.clear()
                if count > 0:
                    st.success(f"Acknowledged {count} item{'s' if count != 1 else ''}.")
                else:
                    st.info("No unacknowledged items found before that date.")
        with col_score:
            st.caption("Acknowledge all items below a score.")
            ack_score = st.number_input("Score threshold", min_value=1, max_value=10, value=5, key="bulk_ack_score")
            if st.button("Acknowledge Below Score", key="bulk_ack_score_btn", type="primary"):
                count = db.acknowledge_below_score(ack_score)
                st.cache_data.clear()
                if count > 0:
                    st.success(f"Acknowledged {count} item{'s' if count != 1 else ''}.")
                else:
                    st.info(f"No unacknowledged items found with score below {ack_score}.")

    # ── Newsletters ──
    with st.expander("Newsletters", expanded=False):
        nl_cfg = cfg.setdefault("newsletters", {"enabled": False, "senders": []})

        nl_enabled = st.toggle(
            "Enable newsletter ingestion",
            value=nl_cfg.get("enabled", False),
            help="Fetch stories from email newsletters via IMAP (runs on daily/open schedule).",
            key="nl_enabled_toggle",
        )
        if nl_enabled != nl_cfg.get("enabled", False):
            nl_cfg["enabled"] = nl_enabled
            save_config(cfg)
            st.rerun()

        if nl_enabled:
            st.markdown("**Email Account**")
            nl_col1, nl_col2 = st.columns(2)
            with nl_col1:
                nl_email = st.text_input(
                    "Email address", value=nl_cfg.get("email", ""),
                    key="nl_email_input", placeholder="newsletters@gmail.com",
                )
                if nl_email != nl_cfg.get("email", ""):
                    nl_cfg["email"] = nl_email
                    save_config(cfg)
            with nl_col2:
                nl_password = st.text_input(
                    "App password", value=nl_cfg.get("password", ""),
                    key="nl_password_input", type="password",
                    help="Gmail App Password. Can also be set via AINEWS_EMAIL_PASSWORD env var.",
                )
                if nl_password != nl_cfg.get("password", ""):
                    nl_cfg["password"] = nl_password
                    save_config(cfg)

            st.markdown("**IMAP Settings**")
            imap_col1, imap_col2, imap_col3 = st.columns(3)
            with imap_col1:
                nl_host = st.text_input(
                    "IMAP host", value=nl_cfg.get("imap_host", "imap.gmail.com"),
                    key="nl_imap_host",
                )
                if nl_host != nl_cfg.get("imap_host", "imap.gmail.com"):
                    nl_cfg["imap_host"] = nl_host
                    save_config(cfg)
            with imap_col2:
                nl_port = st.number_input(
                    "IMAP port", value=nl_cfg.get("imap_port", 993),
                    min_value=1, max_value=65535, key="nl_imap_port",
                )
                if nl_port != nl_cfg.get("imap_port", 993):
                    nl_cfg["imap_port"] = int(nl_port)
                    save_config(cfg)
            with imap_col3:
                nl_max = st.number_input(
                    "Max emails per run", value=nl_cfg.get("max_emails_per_run", 50),
                    min_value=1, max_value=500, key="nl_max_emails",
                )
                if nl_max != nl_cfg.get("max_emails_per_run", 50):
                    nl_cfg["max_emails_per_run"] = int(nl_max)
                    save_config(cfg)

            st.divider()

            st.markdown("**Newsletter Senders**")
            st.caption("Emails from these senders will be processed for news stories.")
            senders = nl_cfg.get("senders", [])

            for si, sender in enumerate(senders):
                s_col1, s_col2, s_col3 = st.columns([3, 5, 0.5])
                s_col1.markdown(f"**{sender.get('name', '')}**")
                s_col2.caption(sender.get("address", ""))
                with s_col3:
                    if st.button("✕", key=f"rm_sender_{si}"):
                        nl_cfg["senders"].pop(si)
                        save_config(cfg)
                        st.rerun()

            st.markdown("**Add Sender**")
            as_col1, as_col2, as_col3 = st.columns([3, 5, 0.5])
            new_sender_name = as_col1.text_input(
                "Name", key="new_sender_name", label_visibility="collapsed",
                placeholder="Newsletter name",
            )
            new_sender_addr = as_col2.text_input(
                "Address", key="new_sender_addr", label_visibility="collapsed",
                placeholder="sender@example.com",
            )
            with as_col3:
                if st.button("Add", key="add_sender", type="primary"):
                    if new_sender_name and new_sender_addr:
                        nl_cfg.setdefault("senders", []).append({
                            "name": new_sender_name,
                            "address": new_sender_addr,
                        })
                        save_config(cfg)
                        st.rerun()

    # ── Sources ──
    with st.expander("Sources", expanded=False):
        feeds = cfg.get("feeds", [])
        queries = cfg.get("search_queries", [])

        # ── Global interval controls ──
        st.markdown("**Scan Intervals**")
        int_col1, int_col2 = st.columns(2)
        with int_col1:
            trusted_options = [10, 15, 30, 60]
            current_trusted = cfg.get("trusted_interval", 15)
            try:
                ti = trusted_options.index(current_trusted)
            except ValueError:
                ti = 1
            new_trusted = st.selectbox(
                "Trusted interval", options=trusted_options, index=ti,
                format_func=lambda x: f"{x} min", key="trusted_interval_sel",
            )
            if new_trusted != current_trusted:
                cfg["trusted_interval"] = new_trusted
                save_config(cfg)
                st.rerun()
        with int_col2:
            open_options = [360, 720, 1440, 2880]
            open_labels = {360: "6 hours", 720: "12 hours", 1440: "24 hours", 2880: "48 hours"}
            current_open = cfg.get("open_interval", 1440)
            try:
                oi = open_options.index(current_open)
            except ValueError:
                oi = 2
            new_open = st.selectbox(
                "Open interval", options=open_options, index=oi,
                format_func=lambda x: open_labels.get(x, f"{x}m"), key="open_interval_sel",
            )
            if new_open != current_open:
                cfg["open_interval"] = new_open
                save_config(cfg)
                st.rerun()

        st.divider()

        # ── Trusted Sources ──
        trusted_feeds = [(i, f) for i, f in enumerate(feeds) if f.get("category", "trusted") == "trusted"]
        trusted_queries = [(i, q) for i, q in enumerate(queries) if q.get("category", "open") == "trusted"]

        st.markdown("**Trusted Sources**")
        st.caption(f"Official vendor feeds — scanned every {cfg.get('trusted_interval', 15)} min.")

        for idx, feed in trusted_feeds:
            feed_type = feed.get("type", "auto")
            is_enabled = feed.get("enabled", True)
            col_toggle, col_type, col_name, col_url, col_cat, col_rm = st.columns([0.4, 0.6, 2, 4, 1.2, 0.4])
            with col_toggle:
                enabled = st.toggle("on", value=is_enabled, key=f"toggle_feed_{idx}", label_visibility="collapsed")
                if enabled != is_enabled:
                    cfg["feeds"][idx]["enabled"] = enabled
                    save_config(cfg)
                    st.rerun()
            col_type.markdown(f"`{feed_type}`")
            name_style = "font-weight:500;" if is_enabled else "font-weight:500;color:var(--text-muted);"
            col_name.markdown(f'<span style="{name_style}">{feed["name"]}</span>', unsafe_allow_html=True)
            col_url.caption(feed["url"])
            with col_cat:
                new_cat = st.selectbox(
                    "Category", options=["trusted", "open"], index=0,
                    key=f"cat_feed_{idx}", label_visibility="collapsed", disabled=not is_enabled,
                )
                if new_cat != "trusted":
                    cfg["feeds"][idx]["category"] = new_cat
                    save_config(cfg)
                    st.rerun()
            with col_rm:
                if st.button("✕", key=f"rm_feed_{idx}"):
                    cfg["feeds"].pop(idx)
                    save_config(cfg)
                    st.rerun()

        for qi, q in trusted_queries:
            query_str = q["query"] if isinstance(q, dict) else q
            col_icon, col_type, col_name, col_cat, col_rm = st.columns([0.4, 0.6, 6, 1.2, 0.4])
            col_icon.markdown("")
            col_type.markdown("`search`")
            col_name.markdown(f"**{query_str}**")
            with col_cat:
                new_cat = st.selectbox(
                    "Category", options=["trusted", "open"], index=0,
                    key=f"cat_query_{qi}", label_visibility="collapsed",
                )
                if new_cat != "trusted":
                    cfg["search_queries"][qi]["category"] = new_cat
                    save_config(cfg)
                    st.rerun()
            with col_rm:
                if st.button("✕", key=f"rm_query_{qi}", type="primary"):
                    cfg["search_queries"].pop(qi)
                    save_config(cfg)
                    st.rerun()

        st.divider()

        # ── Open Sources ──
        open_feeds = [(i, f) for i, f in enumerate(feeds) if f.get("category", "trusted") == "open"]
        open_queries = [(i, q) for i, q in enumerate(queries) if q.get("category", "open") == "open"]

        open_interval_val = cfg.get("open_interval", 1440)
        open_label = open_labels.get(open_interval_val, f"{open_interval_val}m")
        st.markdown("**Open Sources**")
        st.caption(f"General news & web searches — scanned every {open_label}.")

        for idx, feed in open_feeds:
            feed_type = feed.get("type", "auto")
            is_enabled = feed.get("enabled", True)
            col_toggle, col_type, col_name, col_url, col_cat, col_rm = st.columns([0.4, 0.6, 2, 4, 1.2, 0.4])
            with col_toggle:
                enabled = st.toggle("on", value=is_enabled, key=f"toggle_feed_{idx}", label_visibility="collapsed")
                if enabled != is_enabled:
                    cfg["feeds"][idx]["enabled"] = enabled
                    save_config(cfg)
                    st.rerun()
            col_type.markdown(f"`{feed_type}`")
            name_style = "font-weight:500;" if is_enabled else "font-weight:500;color:var(--text-muted);"
            col_name.markdown(f'<span style="{name_style}">{feed["name"]}</span>', unsafe_allow_html=True)
            col_url.caption(feed["url"])
            with col_cat:
                new_cat = st.selectbox(
                    "Category", options=["trusted", "open"], index=1,
                    key=f"cat_feed_{idx}", label_visibility="collapsed", disabled=not is_enabled,
                )
                if new_cat != "open":
                    cfg["feeds"][idx]["category"] = new_cat
                    save_config(cfg)
                    st.rerun()
            with col_rm:
                if st.button("✕", key=f"rm_feed_{idx}"):
                    cfg["feeds"].pop(idx)
                    save_config(cfg)
                    st.rerun()

        for qi, q in open_queries:
            query_str = q["query"] if isinstance(q, dict) else q
            col_icon, col_type, col_name, col_cat, col_rm = st.columns([0.4, 0.6, 6, 1.2, 0.4])
            col_icon.markdown("")
            col_type.markdown("`search`")
            col_name.markdown(f"**{query_str}**")
            with col_cat:
                new_cat = st.selectbox(
                    "Category", options=["trusted", "open"], index=1,
                    key=f"cat_query_{qi}", label_visibility="collapsed",
                )
                if new_cat != "open":
                    cfg["search_queries"][qi]["category"] = new_cat
                    save_config(cfg)
                    st.rerun()
            with col_rm:
                if st.button("✕", key=f"rm_query_{qi}", type="primary"):
                    cfg["search_queries"].pop(qi)
                    save_config(cfg)
                    st.rerun()

        st.divider()

        # ── Add Feed ──
        with st.container():
            st.markdown("**Add Feed**")
            af1, af2, af3, af4, af5 = st.columns([1.2, 1.2, 2, 4, 0.6])
            new_feed_type = af1.selectbox("Type", ["auto", "rss", "web"], key="new_feed_type", label_visibility="collapsed")
            new_feed_cat = af2.selectbox("Category", ["trusted", "open"], key="new_feed_cat", label_visibility="collapsed")
            new_feed_name = af3.text_input("Name", key="new_feed_name", label_visibility="collapsed", placeholder="Feed name")
            new_feed_url = af4.text_input("URL", key="new_feed_url", label_visibility="collapsed", placeholder="https://example.com/feed.xml")
            with af5:
                if st.button("Add", key="add_feed", type="primary"):
                    if new_feed_name and new_feed_url:
                        entry = {"name": new_feed_name, "url": new_feed_url, "enabled": True, "category": new_feed_cat}
                        if new_feed_type != "auto":
                            entry["type"] = new_feed_type
                        cfg.setdefault("feeds", []).append(entry)
                        save_config(cfg)
                        st.rerun()

        # ── Add Search Query ──
        with st.container():
            st.markdown("**Add Search Query**")
            aq1, aq2, aq3 = st.columns([1.2, 7.2, 0.6])
            new_query_cat = aq1.selectbox("Category", ["open", "trusted"], key="new_query_cat", label_visibility="collapsed")
            new_query = aq2.text_input("Query", key="new_query", label_visibility="collapsed", placeholder="e.g. OpenAI news")
            with aq3:
                if st.button("Add", key="add_query", type="primary"):
                    if new_query:
                        cfg.setdefault("search_queries", []).append({"query": new_query, "category": new_query_cat})
                        save_config(cfg)
                        st.rerun()

        st.divider()

        st.markdown("**Source Scan History**")
        source_status = db.get_source_status()
        if not source_status:
            st.info("No scan data yet. Run the fetch pipeline to populate.")
        else:
            for s in source_status:
                col_src, col_count, col_last = st.columns([4, 2, 4])
                col_src.markdown(f"**{s['source']}**")
                col_count.markdown(f"{s['item_count']}")
                col_last.caption(s["last_scanned"])
