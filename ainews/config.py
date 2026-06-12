import os
from pathlib import Path

import yaml


CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


def load_config(path: Path = CONFIG_PATH) -> dict:
    """Load and validate config.yaml, with env var overrides."""
    with open(path) as f:
        cfg = yaml.safe_load(f)

    # Env var takes precedence for API key
    env_key = os.environ.get("ANTHROPIC_API_KEY")
    if env_key:
        cfg["anthropic_api_key"] = env_key

    # Resolve db_path relative to project root
    project_root = Path(__file__).parent.parent
    cfg["db_path"] = str(project_root / cfg.get("db_path", "data/ainews.db"))

    # Defaults
    cfg.setdefault("model", "claude-sonnet-4-5-20250929")
    cfg.setdefault("feeds", [])
    cfg.setdefault("search_queries", [])
    cfg.setdefault("dedup_threshold", 80)
    cfg.setdefault("max_search_results", 5)
    cfg.setdefault("feed_timeout", 15)
    cfg.setdefault("max_items_per_feed", 20)
    cfg.setdefault("categories", ["New Releases", "Research", "Business", "Developer Tools"])
    cfg.setdefault("content_fetching", True)
    cfg.setdefault("content_max_chars", 10000)
    cfg.setdefault("content_score_chars", 3000)

    # Category-based intervals (default: trusted=15min, open=24h)
    cfg.setdefault("trusted_interval", 15)
    cfg.setdefault("open_interval", 1440)

    # Video script (Stage 1 of the daily video pipeline) defaults
    vs = cfg.setdefault("video_script", {})
    vs.setdefault("hours", 24)            # fresh-news window, fills first
    vs.setdefault("catchup_hours", 72)    # older uncovered stories may fill gaps...
    vs.setdefault("catchup_min_score", 8) # ...if they scored at least this
    vs.setdefault("min_score", 6)
    vs.setdefault("max_stories", 7)
    vs.setdefault("target_minutes", 5)
    vs.setdefault("words_per_minute", 155)
    vs.setdefault("show_name", "The Daily Prompt")

    # TTS (Stage 2 of the daily video pipeline) defaults.
    # Provider "elevenlabs" needs ELEVENLABS_API_KEY in the environment and
    # tts.voice set to a voice name/id from the account; falls back to
    # Amazon Polly (instance-role credentials) when no key is present.
    tts = cfg.setdefault("tts", {})
    tts.setdefault("provider", "elevenlabs")
    tts.setdefault("voice", "LtPsVjX1k0Kl4StEMZPK")  # Sophia — Young Australian Female
    tts.setdefault("model", "eleven_multilingual_v2")
    tts.setdefault("speed", 1.15)  # Sophia's natural pace runs slow for news
    tts.setdefault("polly_voice", "Olivia")  # en-AU generative (fallback)
    tts.setdefault("polly_engine", "generative")
    tts.setdefault("region", "us-east-1")
    env_el_key = os.environ.get("ELEVENLABS_API_KEY")
    if env_el_key:
        tts["api_key"] = env_el_key

    # Video render defaults (Stage 3). "lambda" renders distributed on
    # Remotion Lambda (~2-3 min/episode); "local" renders on this machine.
    video = cfg.setdefault("video", {})
    video.setdefault("render_engine", "lambda")
    video.setdefault("lambda_region", "us-east-1")
    video.setdefault("lambda_site", "ainews")
    video.setdefault("assets_bucket", "ainews-render-assets")
    video.setdefault("screenshots", True)  # source-page backdrops per segment

    # Embedding clusterer (owns group_id) — Bedrock Titan via instance role
    emb = cfg.setdefault("embeddings", {})
    emb.setdefault("model_id", "amazon.titan-embed-text-v2:0")
    emb.setdefault("region", "us-east-1")
    emb.setdefault("dimensions", 512)
    emb.setdefault("threshold", 0.80)
    emb.setdefault("window_days", 14)
    emb.setdefault("max_span_days", 4)

    # Newsletter defaults
    nl = cfg.setdefault("newsletters", {"enabled": False, "senders": []})
    nl.setdefault("enabled", False)
    nl.setdefault("imap_host", "imap.gmail.com")
    nl.setdefault("imap_port", 993)
    nl.setdefault("max_emails_per_run", 50)
    nl.setdefault("senders", [])
    # Env var override for email password (avoid plaintext in config on server)
    env_pw = os.environ.get("AINEWS_EMAIL_PASSWORD")
    if env_pw:
        nl["password"] = env_pw

    # Normalize feeds: ensure category field, migrate from scan_interval if needed
    for feed in cfg["feeds"]:
        if "category" not in feed:
            # Migrate: infer category from scan_interval if present
            interval = feed.pop("scan_interval", 15)
            feed["category"] = "open" if interval > 60 else "trusted"
        else:
            feed.pop("scan_interval", None)

    # Normalize search_queries: plain strings become dicts, default category=open
    normalized = []
    for q in cfg.get("search_queries", []):
        if isinstance(q, str):
            normalized.append({"query": q, "category": "open"})
        else:
            if "category" not in q:
                interval = q.pop("scan_interval", 15)
                q["category"] = "open" if interval > 60 else "trusted"
            else:
                q.pop("scan_interval", None)
            normalized.append(q)
    cfg["search_queries"] = normalized

    return cfg


def save_config(cfg: dict, path: Path = CONFIG_PATH):
    """Write config dict back to config.yaml."""
    # Work on a copy to avoid mutating the caller's dict
    to_save = dict(cfg)
    # Restore relative db_path for the file
    project_root = Path(__file__).parent.parent
    try:
        to_save["db_path"] = str(Path(to_save["db_path"]).relative_to(project_root))
    except (ValueError, KeyError):
        pass
    with open(path, "w") as f:
        yaml.dump(to_save, f, default_flow_style=False, sort_keys=False)
