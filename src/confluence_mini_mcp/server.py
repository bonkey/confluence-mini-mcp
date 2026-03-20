"""FastMCP server with tool handlers for Confluence cache."""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from fastmcp import FastMCP, Context
from fastmcp.server.lifespan import lifespan

from .cache import PageCache
from .config import Config, load_config
from .crawler import ConfluenceClient, SubtreeCrawler


@lifespan
async def app_lifespan(server):
    """Initialise cache on startup, tear down client on shutdown."""
    config = load_config()
    cache = PageCache(config)
    client: ConfluenceClient | None = None

    try:
        if config.dry_run:
            print("[DRY-RUN] Server starting in dry-run mode", file=sys.stderr)
            if not cache.load_from_disk():
                cache.load_synthetic()
        else:
            client = ConfluenceClient(config)
            loaded = cache.load_from_disk()

            if loaded and not cache.is_stale():
                # Layer 1: check root versions before serving
                live_versions = SubtreeCrawler(client, config).get_root_versions()
                cached_versions = cache.get_root_versions()
                if live_versions == cached_versions:
                    print("[INFO] Cache is fresh, serving from disk", file=sys.stderr)
                else:
                    print(
                        "[INFO] Root versions changed, re-crawling...", file=sys.stderr
                    )
                    _do_crawl(client, config, cache)
            else:
                reason = "stale" if loaded else "missing"
                print(f"[INFO] Cache {reason}, crawling...", file=sys.stderr)
                _do_crawl(client, config, cache)

        yield {"config": config, "cache": cache, "client": client}
    finally:
        cache.close()
        if client:
            client.close()


def _do_crawl(client: ConfluenceClient, config: Config, cache: PageCache):
    """Run a full crawl and persist to disk."""
    crawler = SubtreeCrawler(client, config)
    pages = crawler.crawl_all()
    root_versions = crawler.get_root_versions()
    cache.update(pages, root_versions)
    cache.save_to_disk()
    print(f"[INFO] Crawled {len(pages)} pages", file=sys.stderr)


mcp = FastMCP("confluence-mini-mcp", lifespan=app_lifespan)


@mcp.tool
def search_pages(query: str, limit: int = 10, ctx: Context = None) -> list[dict]:
    """Full-text search across all cached Confluence pages and external links.

    Returns short snippets only. IMPORTANT: Always call get_page on
    relevant results to read the full content before answering questions.
    The snippet is just a preview — the full page often contains the
    information you need.

    Args:
        query: Space-separated keywords to search for. Try single
            key terms first; the search supports prefix matching.
        limit: Max results to return (default 10, max 20).
    """
    cache: PageCache = ctx.lifespan_context["cache"]
    limit = min(max(limit, 1), 20)
    return cache.search(query, limit)


@mcp.tool
def get_page(page_id: str, ctx: Context = None) -> dict:
    """Retrieve the full Markdown content of a specific page by ID.

    Use this after search_pages to read the complete content of a result.
    Pages may be Confluence pages or crawled external websites.

    Args:
        page_id: The page ID from search_pages or list_pages results.
    """
    cache: PageCache = ctx.lifespan_context["cache"]
    page = cache.get_page(page_id)
    if page is None:
        return {"error": f"Page {page_id} is not in the configured subtrees"}
    return {
        "id": page["id"],
        "title": page["title"],
        "path": page.get("path", []),
        "webUrl": page.get("web_url", ""),
        "spaceKey": page.get("space_key", ""),
        "markdownContent": page.get("markdown_content", ""),
        "lastModified": page.get("last_modified", ""),
        "cachedAt": page.get("cached_at", ""),
        "sourceType": page.get("source_type", "confluence"),
    }


@mcp.tool
def list_pages(space_key: str = "", ctx: Context = None) -> list[dict]:
    """List all cached pages, optionally filtered by space key.

    Args:
        space_key: Optional space key to filter by.
    """
    cache: PageCache = ctx.lifespan_context["cache"]
    pages = cache.all_pages()
    if space_key:
        pages = [p for p in pages if p.get("space_key", "") == space_key]
    return [
        {
            "id": p["id"],
            "title": p["title"],
            "path": p.get("path", []),
            "spaceKey": p.get("space_key", ""),
            "webUrl": p.get("web_url", ""),
            "lastModified": p.get("last_modified", ""),
            "sourceType": p.get("source_type", "confluence"),
        }
        for p in pages
    ]


@mcp.tool
def refresh_cache(ctx: Context = None) -> dict:
    """Force an immediate re-crawl of all configured subtrees, bypassing TTL and version checks."""
    cache: PageCache = ctx.lifespan_context["cache"]
    config: Config = ctx.lifespan_context["config"]
    client: ConfluenceClient | None = ctx.lifespan_context["client"]

    now = datetime.now(timezone.utc).isoformat()

    if config.dry_run:
        print("[DRY-RUN] Skipping refresh_cache — no API calls", file=sys.stderr)
        return {"pagesRefreshed": 0, "crawledAt": now, "dryRun": True}

    if client is None:
        return {"error": "No Confluence client available"}

    _do_crawl(client, config, cache)
    return {
        "pagesRefreshed": len(cache.all_pages()),
        "crawledAt": now,
    }
