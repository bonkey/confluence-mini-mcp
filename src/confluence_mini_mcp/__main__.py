"""Entry point: python -m confluence_mini_mcp"""

import argparse
import sys


def _parse_args():
    parser = argparse.ArgumentParser(
        prog="confluence-mini-mcp",
        description="Confluence MCP server",
    )
    parser.add_argument("command", nargs="?", help="Sub-command (e.g. 'doctor')")
    parser.add_argument("--base-url", dest="base_url", help="Confluence base URL")
    parser.add_argument("--email", help="Confluence user email")
    parser.add_argument("--api-token", dest="api_token", help="Confluence API token")
    parser.add_argument(
        "--root-page-ids",
        dest="root_page_ids",
        help="Comma-separated root page IDs",
    )
    parser.add_argument("--gh-token", dest="gh_token", help="GitHub token")
    parser.add_argument("--cache-dir", dest="cache_dir", help="Cache directory path")
    parser.add_argument(
        "--cache-ttl-minutes", dest="cache_ttl_minutes", help="Cache TTL in minutes"
    )
    parser.add_argument("--max-depth", dest="max_depth", help="Max crawl depth")
    parser.add_argument("--max-pages", dest="max_pages", help="Max pages to crawl")
    parser.add_argument(
        "--refresh-interval-minutes",
        dest="refresh_interval_minutes",
        help="Background refresh interval in minutes",
    )
    parser.add_argument(
        "--dry-run", dest="dry_run", action="store_true", help="Dry-run mode"
    )
    return parser.parse_args()


def main():
    args = _parse_args()

    # Store CLI overrides for load_config to pick up
    from . import config as _config_mod

    _config_mod._cli_args = args

    if args.command == "doctor":
        from .doctor import run_doctor

        sys.exit(run_doctor())

    from .server import mcp

    mcp.run()


if __name__ == "__main__":
    main()
