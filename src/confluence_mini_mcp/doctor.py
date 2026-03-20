"""Doctor command: validate config, connectivity, and cache health."""

from __future__ import annotations

import sys
from pathlib import Path

from .config import load_config, _CONFIG_SEARCH_PATHS


def _ok(msg: str):
    print(f"  ✓ {msg}")


def _warn(msg: str):
    print(f"  ⚠ {msg}")


def _fail(msg: str):
    print(f"  ✗ {msg}")


def run_doctor() -> int:
    """Run all checks. Returns 0 if healthy, 1 if any check failed."""
    failed = False

    # --- Config ---
    print("Config")
    found_file = None
    for path in _CONFIG_SEARCH_PATHS:
        if path.is_file():
            found_file = path
            break
    if found_file:
        _ok(f"Config file: {found_file}")
    else:
        _warn("No config file found (using env vars only)")

    try:
        config = load_config()
        _ok(f"base_url: {config.base_url}")
        _ok(f"email: {config.email}")
        _ok(
            f"api_token: {'*' * min(len(config.api_token), 8)}{'...' if len(config.api_token) > 8 else ''}"
        )
        _ok(f"root_page_ids: {config.root_page_ids}")
        _ok(f"cache_dir: {config.cache_dir}")
        _ok(
            f"max_depth={config.max_depth}  max_pages={config.max_pages}  ttl={config.cache_ttl_minutes}m"
        )
        if config.dry_run:
            _warn("dry_run=true — no API calls will be made")
    except SystemExit:
        _fail("Config loading failed (missing required fields)")
        return 1

    # --- Connectivity ---
    print("\nConnectivity")
    if config.dry_run:
        _warn("Skipped (dry_run mode)")
    else:
        import httpx

        try:
            client = httpx.Client(
                base_url=config.base_url.rstrip("/"),
                auth=(config.email, config.api_token),
                headers={"Accept": "application/json"},
                timeout=15.0,
            )
            # Test auth with a cheap API call
            resp = client.get("/wiki/api/v2/spaces", params={"limit": 1})
            if resp.status_code == 200:
                _ok(f"Confluence API reachable ({config.base_url})")
            elif resp.status_code == 401:
                _fail("Authentication failed (401) — check email/api_token")
                failed = True
            elif resp.status_code == 403:
                _fail("Forbidden (403) — token may lack permissions")
                failed = True
            else:
                _warn(f"Unexpected status {resp.status_code} from spaces endpoint")
            client.close()
        except httpx.ConnectError:
            _fail(f"Cannot connect to {config.base_url} — check base_url and network")
            failed = True
        except httpx.HTTPError as exc:
            _fail(f"HTTP error: {exc}")
            failed = True

        # Test root page access
        for root_id in config.root_page_ids:
            try:
                client = httpx.Client(
                    base_url=config.base_url.rstrip("/"),
                    auth=(config.email, config.api_token),
                    headers={"Accept": "application/json"},
                    timeout=15.0,
                )
                resp = client.get(
                    f"/api/v2/pages/{root_id}", params={"body-format": "storage"}
                )
                if resp.status_code == 200:
                    title = resp.json().get("title", "?")
                    _ok(f'Root page {root_id}: "{title}"')
                elif resp.status_code == 404:
                    _fail(f"Root page {root_id}: not found (404)")
                    failed = True
                else:
                    _warn(f"Root page {root_id}: status {resp.status_code}")
                client.close()
            except httpx.HTTPError as exc:
                _fail(f"Root page {root_id}: {exc}")
                failed = True

    # --- Cache ---
    print("\nCache")
    db_path = config.cache_dir / "cache.db"
    if not db_path.is_file():
        _warn(f"No cache file at {db_path} (will be created on first run)")
    else:
        import sqlite3

        size_mb = db_path.stat().st_size / (1024 * 1024)
        _ok(f"Cache file: {db_path} ({size_mb:.1f} MB)")
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            count = conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
            _ok(f"Cached pages: {count}")

            crawled_at = conn.execute(
                "SELECT value FROM meta WHERE key = 'crawled_at'"
            ).fetchone()
            if crawled_at:
                _ok(f"Last crawled: {crawled_at[0]}")
            else:
                _warn("No crawled_at timestamp in cache")

            conn.close()
        except sqlite3.Error as exc:
            _fail(f"Cache DB error: {exc}")
            failed = True

    print()
    if failed:
        print("Some checks failed. Fix the issues above and re-run.")
        return 1
    else:
        print("All checks passed!")
        return 0
