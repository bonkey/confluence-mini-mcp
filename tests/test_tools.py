"""Integration test: all 4 MCP tools in dry-run mode."""

import asyncio
import json

from fastmcp import Client
from confluence_mini_mcp.server import mcp


async def test():
    async with Client(mcp) as client:
        r = await client.call_tool("list_pages", {})
        pages = json.loads(r.content[0].text)
        assert len(pages) > 0, "list_pages returned no pages"

        r = await client.call_tool("search_pages", {"query": "deploy"})
        results = json.loads(r.content[0].text)
        assert len(results) > 0, "search returned no results"

        r = await client.call_tool("get_page", {"page_id": pages[0]["id"]})
        page = json.loads(r.content[0].text)
        assert "markdownContent" in page, "get_page missing content"

        r = await client.call_tool("get_page", {"page_id": "nonexistent"})
        page = json.loads(r.content[0].text)
        assert "error" in page, "get_page should error on unknown ID"

        r = await client.call_tool("refresh_cache", {})
        refresh = json.loads(r.content[0].text)
        assert "dryRun" in refresh, "refresh_cache should indicate dry run"

        print("All tests passed")


if __name__ == "__main__":
    asyncio.run(test())
