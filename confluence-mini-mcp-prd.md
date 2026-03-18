# PRD: confluence-mini-mcp

---

## Overview

A lightweight MCP server that crawls a scoped subtree of Confluence pages, caches them on disk as Markdown, and exposes that content to AI agents via three focused tools. Both Claude Code and [nanobot](https://github.com/HKUDS/nanobot) (a lightweight AI agent connected to Slack) launch it as a stdio child process. The goal is fast, accurate access to a curated slice of Confluence — not the entire workspace.

---

## Problem

Claude Code agents frequently need to reference internal documentation during coding tasks. The full Confluence MCP (mcp-atlassian) is too broad: it queries live API endpoints on every tool call, introduces latency, burns API rate limits, and gives the agent access to the entire workspace rather than the relevant branch of docs. For tightly scoped workflows (e.g. a specific service's runbooks, a project's specs), this is wasteful and noisy.

---

## Goals

- Sub-100ms tool response time for search and retrieval (served from local cache)
- Crawl only explicitly configured page subtrees — nothing else is accessible
- Smart cache refresh: avoid unnecessary re-crawls, only refetch what actually changed
- Minimal dependencies: Python 3.11+, FastMCP (pinned), `httpx`, `markdownify` — works on the Mac Mini with `uvx` or `pip install`
- Drop-in compatible with Claude Code's MCP config (`~/.claude/claude_desktop_config.json`)

## Non-goals

- Full Confluence write support (create/update pages) — read-only
- Semantic / vector search — keyword scoring is sufficient for the target use case
- Remote HTTP deployment in v1 — stdio only (both Claude Code and nanobot launch it locally)
- Support for Confluence Server / Data Center in v1 — Cloud API only

---

## Users

**Primary:** iOS developers using selected Confluence trees via Claude Code. Agents need to reference project specs, architecture decisions, and runbooks without leaving the terminal.

**Secondary:** Team members querying Confluence docs through Slack via [nanobot](https://github.com/HKUDS/nanobot). Nanobot launches the server as a local stdio MCP child process, discovers its tools, and wraps them as native agent tools (`mcp_confluence_*`) — any Slack user in the channel can search and retrieve docs conversationally.

---

## Core Concepts

### Subtree

A "subtree" is a Confluence page and all its descendants, defined by a single root page ID. The server accepts one or more root page IDs in config. All crawling, caching, and tool scoping is bounded by those roots.

### Cache

A local `~/.cache/confluence-subtree-mcp/index.json` file containing all crawled pages as Markdown with metadata. The cache is the source of truth for all tool calls. It is rebuilt from Confluence only when invalidation conditions are met. The cache directory follows the XDG convention and lives outside the project tree.

### Smart refresh

The server uses Confluence's `version.when` field to detect changes cheaply. On startup and optionally on a background interval, it polls only the root page(s) and their immediate descendants for version timestamps — a handful of API calls regardless of subtree size. If any page's version timestamp has advanced since the last crawl, only the affected subtree branch is re-crawled.

---

## Configuration

Config is resolved in priority order: `confluence-mini-mcp.toml` (next to the package or in `~/.config/confluence-mini-mcp/`) → environment variables.

| TOML key                 | Env var                        | Description                                                                | Default                              |
| ------------------------ | ------------------------------ | -------------------------------------------------------------------------- | ------------------------------------ |
| `base_url`               | `CONFLUENCE_BASE_URL`          | Base URL of the Confluence wiki, e.g. `https://company.atlassian.net/wiki` | required                             |
| `email`                  | `CONFLUENCE_EMAIL`             | Atlassian account email                                                    | required                             |
| `api_token`              | `CONFLUENCE_API_TOKEN`         | Atlassian API token                                                        | required                             |
| `root_page_ids`          | `CONFLUENCE_ROOT_PAGE_IDS`     | Array of page IDs (TOML) / comma-separated (env) to use as subtree roots  | required                             |
| `cache_dir`              | `CONFLUENCE_CACHE_DIR`         | Path to local cache directory                                              | `~/.cache/confluence-subtree-mcp`    |
| `cache_ttl_minutes`      | `CONFLUENCE_CACHE_TTL_MINUTES` | Maximum age of cache before a forced re-crawl                              | `30`                                 |
| `max_depth`              | `CONFLUENCE_MAX_DEPTH`         | Maximum recursion depth from each root                                     | `10`                                 |
| `max_pages`              | `CONFLUENCE_MAX_PAGES`         | Hard cap on total pages crawled across all roots                           | `500`                                |
| `refresh_interval_minutes` | `CONFLUENCE_REFRESH_INTERVAL`| Background version-check interval (0 = disabled)                           | `5`                                  |
| `dry_run`                | `CONFLUENCE_DRY_RUN`           | Fake-cache mode: skip all Confluence API calls and disk writes, serve synthetic/stale data (see below) | `false`              |

---

## MCP Tools

### `search_pages`

Full-text search across all cached pages in the configured subtrees.

**Input:**

```json
{
  "query": "string — space-separated keywords",
  "limit": "number (optional, default 10, max 20)"
}
```

**Output:** Array of results, each containing:

- `id` — Confluence page ID
- `title` — page title
- `path` — breadcrumb array of ancestor titles
- `webUrl` — direct link to the page in Confluence
- `snippet` — first ~300 chars of content containing the matched terms
- `score` — relevance score (for debugging/transparency)

**Scoring:** Title matches are weighted 10x over body matches. Occurrence count in body is capped at 20 per term to prevent very long pages from dominating.

---

### `get_page`

Retrieve the full Markdown content of a specific page by ID.

**Input:**

```json
{
  "page_id": "string"
}
```

**Output:**

- `id`, `title`, `path`, `webUrl`, `spaceKey`
- `markdownContent` — full page content converted from Confluence storage format to Markdown
- `lastModified` — ISO timestamp from Confluence
- `cachedAt` — ISO timestamp of when this was last fetched

Returns an error if the page ID is not in the cache (i.e. not within the configured subtrees).

---

### `list_pages`

List all pages in the cache, optionally filtered by space key.

**Input:**

```json
{
  "space_key": "string (optional)"
}
```

**Output:** Array of `{ id, title, path, spaceKey, webUrl, lastModified }` — no content, just the index. Useful for the agent to understand what's available before searching.

---

### `refresh_cache`

Force an immediate re-crawl of all configured subtrees, bypassing TTL and version checks.

**Input:** none

**Output:** `{ pagesRefreshed: number, crawledAt: string }`

Use when docs are known to have been updated and waiting for the next automatic check is not acceptable.

---

## Cache Invalidation — Smart Refresh Policy

This is the core engineering decision. The policy has three layers:

### Layer 1 — Startup version check (always runs)

On process start, before serving any tool calls:

1. For each `rootPageId`, fetch the page metadata from Confluence (title, `version.when`, child count) — one API call per root.
2. Compare `version.when` against the value stored in the cache index.
3. If unchanged for all roots → serve from cache immediately, no crawl.
4. If any root has changed → perform a selective re-crawl of only that root's subtree (see Layer 3).

This means cold starts after no doc changes are near-instant (a few API calls, then in-memory load). Cold starts after a doc change pay the crawl cost only for the affected branch.

### Layer 2 — Background polling (optional, configurable)

If `refreshIntervalMinutes > 0`, a background `setInterval` runs the same version check as Layer 1. It never blocks tool calls. If it detects a change, it silently updates the cache. The next tool call after the background update gets fresh data.

Disabled by default to keep the process completely idle when not in use. Recommended value when enabled: 15 minutes.

### Layer 3 — Selective subtree re-crawl

When a root page's version has changed, the server re-crawls only that root's subtree:

1. Walk the live Confluence subtree, collecting `{ id, version.when }` for every page — one API call per page, but only for the changed root.
2. Diff against cached versions.
3. Re-fetch full content only for pages whose `version.when` has advanced.
4. Remove cached entries for pages that no longer exist in the subtree (deleted/moved).
5. Merge into the existing cache index and write to disk.

This means a single page edit anywhere in a large subtree costs: 1 API call per page in that subtree (version check) + 1 API call for the changed page (content fetch).

### Layer 4 — TTL hard ceiling

Regardless of version check results, if the cache is older than `cacheTtlMinutes`, force a full re-crawl of all roots. This is a safety net for edge cases (version field not updating correctly, manual Confluence migrations, etc.).

---

## Dry-Run Mode (Fake Cache)

When `dryRun` is `true` (or `CONFLUENCE_DRY_RUN=true`), the server operates without touching Confluence or writing to disk. This is for development and integration testing — you can wire up Claude Code or the nanobot and exercise all tool calls without real credentials or network access.

### Behaviour

| Operation | Normal mode | Dry-run mode |
| --- | --- | --- |
| Startup crawl | Fetches from Confluence API | Skipped — loads existing cache file if present, or generates a small set of synthetic pages |
| Background refresh | Polls Confluence for version changes | Skipped entirely (no timers started) |
| `refresh_cache` tool | Re-crawls live subtrees | Returns `{ pagesRefreshed: 0, crawledAt: "...", dryRun: true }` — no API calls |
| `search_pages` / `get_page` / `list_pages` | Reads from cache | Reads from cache (real if one exists, synthetic if not) |
| Cache writes | Writes `index.json` to disk | No disk writes — cache lives in memory only |

### Synthetic pages

When no existing cache file is found in dry-run mode, the server generates 5 placeholder pages with lorem-ipsum content, realistic metadata, and a shallow hierarchy. This ensures tools always return non-empty results during development.

### Logging

All skipped operations are logged to stderr with a `[DRY-RUN]` prefix so it's obvious the server is not hitting real data.

---

## HTML → Markdown Conversion

Confluence stores page content in "storage format" (a proprietary XHTML dialect). The server converts this to clean Markdown at cache time, so tool outputs are immediately usable by agents without further processing.

Conversion requirements:

- Headings (`<h1>`–`<h6>`) → ATX Markdown headings
- Bold/italic inline formatting
- Bullet and numbered lists
- Links (including Confluence internal links resolved to full URLs)
- Code blocks (`<ac:structured-macro ac:name="code">`) → fenced code blocks, preserving language hint if present
- Tables → GitHub-flavoured Markdown tables
- Strip Confluence-specific macros that don't have a Markdown equivalent (info/warning panels reduced to blockquotes with a label)
- Decode all HTML entities

The conversion is intentionally lossy for layout — the goal is readable, greppable text for an agent, not a pixel-perfect render.

---

## Transport

stdio only. The server is launched as a child process and communicates over stdin/stdout using the MCP JSON-RPC protocol. Both Claude Code and nanobot use this model.

Claude Code config (`~/.claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "confluence-docs": {
      "command": "uvx",
      "args": ["confluence-mini-mcp"],
      "env": {
        "CONFLUENCE_BASE_URL": "https://company.atlassian.net/wiki",
        "CONFLUENCE_EMAIL": "daniel@company.com",
        "CONFLUENCE_API_TOKEN": "...",
        "CONFLUENCE_ROOT_PAGE_IDS": "123456,789012"
      }
    }
  }
}
```

Nanobot config (`nanobot.toml`):

```toml
[mcp.confluence]
command = "uvx"
args = ["confluence-mini-mcp"]
env = { CONFLUENCE_BASE_URL = "https://company.atlassian.net/wiki", CONFLUENCE_EMAIL = "daniel@company.com", CONFLUENCE_API_TOKEN = "...", CONFLUENCE_ROOT_PAGE_IDS = "123456,789012" }
# enabledTools = ["search_pages", "get_page", "list_pages"]  # optional filter
```

Or, if installed via pip or from a local checkout, using `python -m confluence_mini_mcp` instead of `uvx`.

---

## Error Handling

| Scenario                              | Behaviour                                                                       |
| ------------------------------------- | ------------------------------------------------------------------------------- |
| Missing required config               | Log clear error to stderr, exit with code 1 before starting the server          |
| Confluence API auth failure           | Log to stderr, surface error in tool response, serve stale cache if available   |
| Confluence API rate limit (429)       | Exponential backoff, max 3 retries, then log and serve stale cache              |
| Page fetch failure during crawl       | Skip the page, log a warning, continue crawl — do not fail the entire operation |
| Cache file corrupted/unreadable       | Delete and trigger a full re-crawl                                              |
| `get_page` called with unknown ID     | Return a clear error: `"Page {id} is not in the configured subtrees"`           |
| `maxPages` limit reached during crawl | Stop crawling, log a warning with count, serve what was collected               |

---

## File Structure

```
confluence-mini-mcp/
├── src/
│   └── confluence_mini_mcp/
│       ├── __init__.py
│       ├── __main__.py    # Entry point (python -m confluence_mini_mcp)
│       ├── server.py      # FastMCP server + @mcp.tool handlers
│       ├── crawler.py     # Confluence API client + subtree walker
│       ├── cache.py       # Cache read/write/invalidation
│       └── converter.py   # HTML storage format → Markdown
├── pyproject.toml
└── confluence-mini-mcp.toml  # Optional config file (gitignored)
```

Cache lives at `~/.cache/confluence-subtree-mcp/` (outside the repo). The optional `confluence-mini-mcp.toml` should be in `.gitignore`.

---

## Implementation Phases

### Phase 1 — Working local server

- Config loading (file + env vars)
- Full subtree crawl on first run
- Disk cache with TTL-based invalidation
- Three tools: `search_pages`, `get_page`, `list_pages`
- HTML → Markdown conversion
- stdio MCP transport
- `refresh_cache` tool
- Dry-run mode (`dryRun` / `CONFLUENCE_DRY_RUN`)

**Done when:** Claude Code and nanobot can both search and retrieve pages via stdio. Dry-run mode works end-to-end without Confluence credentials.

### Phase 2 — Smart refresh

- Startup version check (Layer 1)
- Selective subtree re-crawl (Layer 3)
- Background polling interval (Layer 2, disabled by default)

**Done when:** An agent restarting Claude Code after a doc update gets fresh content without a full re-crawl.

### Phase 3 — Polish

- `--inspect` CLI flag: dumps cache index to stdout as a table (title, id, path, lastModified, size) for manual verification
- `--crawl-only` CLI flag: crawls and exits — useful in CI or as a cron job to pre-warm the cache
- Configurable per-root max depth (array in config, parallel to `rootPageIds`)
- Snippet highlighting in `search_pages` results (bold matched terms in snippet)

---

## Open Questions

1. **Multiple configs for multiple projects** — should the server support loading multiple named config profiles, or is one instance per project (separate MCP entries in Claude Code config) the right model? Leaning toward one instance per project for simplicity and isolation.

2. **Content truncation** — `get_page` returns full Markdown. Very long pages (e.g. 50k tokens) could blow the context window. Should there be a `max_tokens` parameter, or a `get_page_section` tool that takes a heading as a second argument?

3. **Upgrade path to HTTP** — if the server ever needs to run as a shared remote service (e.g. for multiple nanobot instances), the architecture should make it easy to swap in an HTTP/SSE transport later without rewriting the core logic. Not needed in v1 since nanobot launches it as a local stdio child process.
