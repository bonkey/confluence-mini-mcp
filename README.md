# confluence-mini-mcp

Lightweight MCP server that crawls Confluence subtrees and serves cached Markdown. Works with Claude Code and [nanobot](https://github.com/HKUDS/nanobot) (Slack) via stdio.

## Claude Code config

```json
{
  "mcpServers": {
    "confluence-docs": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/bonkey/confluence-mini-mcp", "confluence-mini-mcp"],
      "env": {
        "CONFLUENCE_BASE_URL": "https://company.atlassian.net/wiki",
        "CONFLUENCE_EMAIL": "you@company.com",
        "CONFLUENCE_API_TOKEN": "...",
        "CONFLUENCE_ROOT_PAGE_IDS": "123456,789012"
      }
    }
  }
}
```

Pin to a tag: `"--from", "git+https://github.com/bonkey/confluence-mini-mcp@v0.1.1"`

## Nanobot config

```toml
[mcp.confluence]
command = "uvx"
args = ["--from", "git+https://github.com/bonkey/confluence-mini-mcp", "confluence-mini-mcp"]
env = { CONFLUENCE_BASE_URL = "https://company.atlassian.net/wiki", CONFLUENCE_EMAIL = "you@company.com", CONFLUENCE_API_TOKEN = "...", CONFLUENCE_ROOT_PAGE_IDS = "123456,789012" }
```

## Tools

| Tool | Description |
|------|-------------|
| `search_pages` | Keyword search across cached pages (title 10x weight) |
| `get_page` | Full Markdown content by page ID (Confluence or external) |
| `list_pages` | Index of all cached pages (optional space_key filter) |
| `refresh_cache` | Force re-crawl, bypass TTL |

## Crawling

The crawler walks a **graph**, not just a tree:

- **Child pages** — standard parent → children traversal
- **Linked Confluence pages** — any internal link in page content is followed (enables a single "hub page" linking to multiple subtrees)
- **External HTTP links** — fetched as Markdown (1 level deep, follows redirects only)

### In-page directives

Add a `[confluence-mcp]` block anywhere on a Confluence page to control crawl behaviour for that subtree:

```
[confluence-mcp]
max_depth=3
follow_links=false
follow_external=true
```

| Directive | Default | Description |
|-----------|---------|-------------|
| `max_depth` | (global config) | Override crawl depth from this page down |
| `follow_links` | `true` | Follow linked Confluence pages in content |
| `follow_external` | `true` | Fetch external HTTP links in content |

The directive block is stripped from the Markdown output — agents never see it.

## Configuration

All settings via env vars or `confluence-mini-mcp.toml`:

| Env var | Description | Default |
|---------|-------------|---------|
| `CONFLUENCE_BASE_URL` | Wiki base URL | required |
| `CONFLUENCE_EMAIL` | Atlassian email | required |
| `CONFLUENCE_API_TOKEN` | API token | required |
| `CONFLUENCE_ROOT_PAGE_IDS` | Comma-separated root page IDs | required |
| `CONFLUENCE_CACHE_DIR` | Cache directory | `~/.cache/confluence-subtree-mcp` |
| `CONFLUENCE_CACHE_TTL_MINUTES` | Cache max age | `30` |
| `CONFLUENCE_MAX_DEPTH` | Max crawl depth | `10` |
| `CONFLUENCE_MAX_PAGES` | Max pages to crawl | `500` |
| `CONFLUENCE_REFRESH_INTERVAL` | Background refresh interval (0=off) | `5` |
| `CONFLUENCE_DRY_RUN` | Fake cache mode, no API calls | `false` |

## Development

```bash
just dev     # run in dry-run mode
just check   # format + test
just release # tag + push
```

All tasks in the [Justfile](Justfile). Requires [uv](https://docs.astral.sh/uv/) and [just](https://github.com/casey/just).
