import copy
import os
import tempfile
from pathlib import Path

import yaml


CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

# Secrets that may come from the environment instead of config.yaml:
# (env var, key path inside cfg). Env values win on load and are never
# written back to disk by save_config.
_ENV_SECRETS = (
    ("ANTHROPIC_API_KEY", ("anthropic_api_key",)),
    ("ELEVENLABS_API_KEY", ("tts", "api_key")),
    ("AINEWS_EMAIL_PASSWORD", ("newsletters", "password")),
)


def _read_raw(path: Path) -> dict:
    """The file's own contents, without defaults or env overrides."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _apply_env_secrets(cfg: dict) -> None:
    for env_var, key_path in _ENV_SECRETS:
        value = os.environ.get(env_var)
        if value:
            target = cfg
            for key in key_path[:-1]:
                target = target.setdefault(key, {})
            target[key_path[-1]] = value


def load_config(path: Path = CONFIG_PATH) -> dict:
    """Load and validate config.yaml, with env var overrides."""
    cfg = _apply_defaults(_read_raw(path))
    _apply_env_secrets(cfg)
    return cfg


def _apply_defaults(cfg: dict) -> dict:
    """Fill code defaults and normalize legacy keys (mutates and returns cfg)."""
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
    emb.setdefault("borderline_low", 0.45)  # two-stage dedup: LLM judges [0.45, 0.80)
    emb.setdefault("llm_dedup", True)

    # Email newsletter (SES) defaults. Set from_address + recipients to enable.
    nlw = cfg.setdefault("newsletter", {})
    nlw.setdefault("enabled", False)
    nlw.setdefault("from_address", "")          # e.g. "The Daily Prompt <news@eyrean.com>"
    nlw.setdefault("recipients", [])
    nlw.setdefault("ses_region", "us-west-1")
    nlw.setdefault("min_score", 6)
    nlw.setdefault("max_stories", 12)
    nlw.setdefault("site_url", "https://ainews.eyrean.com")
    nlw.setdefault("unsubscribe_address", "")

    # Newsletter (IMAP ingestion) defaults
    nl = cfg.setdefault("newsletters", {"enabled": False, "senders": []})
    nl.setdefault("enabled", False)
    nl.setdefault("imap_host", "imap.gmail.com")
    nl.setdefault("imap_port", 993)
    nl.setdefault("max_emails_per_run", 50)
    nl.setdefault("senders", [])

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


def _merge_changes(out: dict, base: dict, new: dict, skip: set, path: tuple = ()) -> None:
    """Apply to ``out`` (the file's raw dict) only what differs between
    ``new`` (the caller's edited cfg) and ``base`` (what load_config would
    produce from the file, minus env). Keys under ``skip`` are left alone."""
    for key, value in new.items():
        key_path = path + (key,)
        if key_path in skip:
            continue
        base_value = base.get(key)
        if isinstance(value, dict) and isinstance(base_value, dict):
            sub_out = out.get(key) if isinstance(out.get(key), dict) else {}
            _merge_changes(sub_out, base_value, value, skip, key_path)
            if sub_out or key in out:
                out[key] = sub_out
        elif key not in base or base_value != value:
            out[key] = copy.deepcopy(value)
    for key in list(out):
        if key in base and key not in new and path + (key,) not in skip:
            del out[key]


def save_config(cfg: dict, path: Path = CONFIG_PATH):
    """Persist the caller's edits to config.yaml.

    Writes only what the caller changed relative to the file: code defaults
    filled in by load_config stay out of the file (so later default changes
    still take effect), and secrets supplied via environment variables are
    never written to disk. The write is atomic and owner-only (0600).
    """
    path = Path(path)
    raw = _read_raw(path) if path.exists() else {}
    base = _apply_defaults(copy.deepcopy(raw))
    skip = {key_path for env_var, key_path in _ENV_SECRETS if os.environ.get(env_var)}

    out = copy.deepcopy(raw)
    _merge_changes(out, base, cfg, skip)

    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".config.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.dump(out, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
