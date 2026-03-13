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
                q["category"] = "open" if interval > 60 else "open"
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
