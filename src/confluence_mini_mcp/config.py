"""Configuration loading: TOML file → env vars → defaults."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]


_CONFIG_FILENAME = "confluence-mini-mcp.toml"

_CONFIG_SEARCH_PATHS = [
    Path.cwd() / _CONFIG_FILENAME,
    Path.home() / ".config" / "confluence-mini-mcp" / _CONFIG_FILENAME,
]


@dataclass
class Config:
    base_url: str
    email: str
    api_token: str
    root_page_ids: list[str]
    cache_dir: Path = field(
        default_factory=lambda: Path.home() / ".cache" / "confluence-subtree-mcp"
    )
    cache_ttl_minutes: int = 30
    max_depth: int = 10
    max_pages: int = 500
    refresh_interval_minutes: int = 5
    gh_token: str = ""
    dry_run: bool = False


def load_config() -> Config:
    """Load config from TOML file (if found) merged with env vars."""
    file_values: dict = {}
    for path in _CONFIG_SEARCH_PATHS:
        if path.is_file():
            with open(path, "rb") as f:
                file_values = tomllib.load(f)
            break

    def _get(key: str, env_key: str, default=None):
        return os.environ.get(env_key) or file_values.get(key) or default

    base_url = _get("base_url", "CONFLUENCE_BASE_URL")
    email = _get("email", "CONFLUENCE_EMAIL")
    api_token = _get("api_token", "CONFLUENCE_API_TOKEN")
    gh_token = _get("gh_token", "GH_TOKEN", "")
    dry_run = _str_to_bool(_get("dry_run", "CONFLUENCE_DRY_RUN", "false"))

    # root_page_ids: TOML array or comma-separated env var
    root_page_ids_raw = os.environ.get("CONFLUENCE_ROOT_PAGE_IDS") or file_values.get(
        "root_page_ids"
    )
    if isinstance(root_page_ids_raw, str):
        root_page_ids = [s.strip() for s in root_page_ids_raw.split(",") if s.strip()]
    elif isinstance(root_page_ids_raw, list):
        root_page_ids = [str(x) for x in root_page_ids_raw]
    else:
        root_page_ids = []

    if not dry_run:
        missing = []
        if not base_url:
            missing.append("base_url / CONFLUENCE_BASE_URL")
        if not email:
            missing.append("email / CONFLUENCE_EMAIL")
        if not api_token:
            missing.append("api_token / CONFLUENCE_API_TOKEN")
        if not root_page_ids:
            missing.append("root_page_ids / CONFLUENCE_ROOT_PAGE_IDS")
        if missing:
            print(
                f"ERROR: Missing required config: {', '.join(missing)}", file=sys.stderr
            )
            sys.exit(1)

    default_cache_dir = Path.home() / ".cache" / "confluence-subtree-mcp"
    cache_dir_raw = _get("cache_dir", "CONFLUENCE_CACHE_DIR")
    cache_dir = Path(cache_dir_raw).expanduser() if cache_dir_raw else default_cache_dir

    return Config(
        base_url=base_url or "",
        email=email or "",
        api_token=api_token or "",
        root_page_ids=root_page_ids,
        cache_dir=cache_dir,
        cache_ttl_minutes=int(
            _get("cache_ttl_minutes", "CONFLUENCE_CACHE_TTL_MINUTES", "30")
        ),
        max_depth=int(_get("max_depth", "CONFLUENCE_MAX_DEPTH", "10")),
        max_pages=int(_get("max_pages", "CONFLUENCE_MAX_PAGES", "500")),
        refresh_interval_minutes=int(
            _get("refresh_interval_minutes", "CONFLUENCE_REFRESH_INTERVAL", "5")
        ),
        gh_token=gh_token,
        dry_run=dry_run,
    )


def _str_to_bool(val: str) -> bool:
    return val.lower() in ("true", "1", "yes")
