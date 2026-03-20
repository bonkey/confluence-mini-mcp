"""Confluence API client and subtree crawler.

The crawler walks a graph, not just a tree:
- Child pages (parent → children)
- Linked Confluence pages (page content → linked pages)
- External HTTP links (page content → external URLs, 1 level deep)
"""

from __future__ import annotations

import re
import sys
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from .config import Config
from .converter import confluence_to_markdown
from .directives import parse_directives_from_html, strip_directive_block


@dataclass
class PageData:
    id: str
    title: str
    space_key: str
    path: list[str]
    web_url: str
    markdown_content: str
    last_modified: str
    version_when: str
    source_type: str = "confluence"  # "confluence" or "external"


class ConfluenceClient:
    """Thin wrapper around the Confluence Cloud REST API v2."""

    def __init__(self, config: Config):
        self._config = config
        self._base = config.base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self._base,
            auth=(config.email, config.api_token),
            headers={"Accept": "application/json"},
            timeout=30.0,
        )

    def close(self):
        self._client.close()

    def _get(self, url: str, params: dict | None = None) -> dict:
        """GET with retry on 429."""
        retries = 0
        while True:
            resp = self._client.get(url, params=params)
            if resp.status_code == 429 and retries < 3:
                import time

                wait = 2**retries
                print(
                    f"[WARN] Rate limited (429), retrying in {wait}s...",
                    file=sys.stderr,
                )
                time.sleep(wait)
                retries += 1
                continue
            resp.raise_for_status()
            return resp.json()

    def get_page_metadata(self, page_id: str) -> dict:
        """Fetch page metadata including version info."""
        return self._get(
            f"/api/v2/pages/{page_id}",
            params={"body-format": "storage"},
        )

    def get_page_with_body(self, page_id: str) -> dict:
        """Fetch a page with its storage-format body."""
        return self._get(
            f"/api/v2/pages/{page_id}",
            params={"body-format": "storage"},
        )

    def find_page_by_title(self, title: str, space_key: str = "") -> str | None:
        """Resolve a page title to its ID. Returns None if not found."""
        params: dict = {"title": title, "limit": 1}
        if space_key:
            params["space-key"] = space_key
        try:
            data = self._get("/api/v2/pages", params=params)
            results = data.get("results", [])
            if results:
                return str(results[0]["id"])
        except httpx.HTTPStatusError:
            pass
        return None

    def get_child_pages(self, page_id: str) -> list[dict]:
        """Fetch all direct child pages of a given page."""
        results = []
        url = f"/api/v2/pages/{page_id}/children"
        params: dict = {"limit": 50}
        while True:
            data = self._get(url, params=params)
            results.extend(data.get("results", []))
            next_link = data.get("_links", {}).get("next")
            if not next_link:
                break
            url = next_link
            params = {}
        return results


# ---------------------------------------------------------------------------
# Link extraction from Confluence storage format HTML
# ---------------------------------------------------------------------------


def extract_confluence_page_ids(html: str) -> list[str]:
    """Extract linked Confluence page IDs from storage-format HTML.

    Confluence internal links look like:
      <ac:link><ri:page ri:content-title="..." ri:space-key="..." /><ri:page ri:page-id="12345" /></ac:link>
      <a href="/wiki/spaces/SPACE/pages/12345/Title">...</a>
    """
    ids: list[str] = []

    # ri:page with explicit page-id
    for m in re.finditer(r'ri:page-id="(\d+)"', html):
        ids.append(m.group(1))

    # href links to /wiki/spaces/.../pages/<id>/...
    for m in re.finditer(r'href="[^"]*?/pages/(\d+)(?:/[^"]*?)?"', html):
        ids.append(m.group(1))

    return list(dict.fromkeys(ids))  # dedupe, preserve order


def extract_macro_page_refs(html: str) -> list[tuple[str, str]]:
    """Extract page references from Confluence macros (include, excerpt-include, children).

    These macros reference pages by title (not ID), wrapped in:
        <ri:page ri:content-title="Page Title" ri:space-key="SPACE" />

    Returns a list of (title, space_key) tuples. space_key may be empty
    if the macro references a page in the same space.
    """
    refs: list[tuple[str, str]] = []

    # Match ri:page with content-title inside structured macros
    # These appear in include, excerpt-include, and children macros
    for m in re.finditer(
        r'<ri:page[^>]*\bri:content-title="([^"]+)"[^>]*/?>',
        html,
    ):
        title = m.group(1)
        # Check for space-key in the same tag
        sk = re.search(r'ri:space-key="([^"]+)"', m.group(0))
        space_key = sk.group(1) if sk else ""
        refs.append((title, space_key))

    return list(dict.fromkeys(refs))  # dedupe, preserve order


def extract_external_urls(html: str, confluence_base: str) -> list[str]:
    """Extract external HTTP(S) URLs from storage-format HTML."""
    urls: list[str] = []
    confluence_host = urlparse(confluence_base).netloc.lower()

    for m in re.finditer(r'href="(https?://[^"]+)"', html):
        url = m.group(1)
        host = urlparse(url).netloc.lower()
        if host and host != confluence_host:
            urls.append(url)

    return list(dict.fromkeys(urls))  # dedupe


# ---------------------------------------------------------------------------
# External URL fetcher
# ---------------------------------------------------------------------------


def _is_github_url(url: str) -> bool:
    """Check if a URL points to GitHub or GitHub raw content."""
    host = urlparse(url).netloc.lower()
    return host in ("github.com", "raw.githubusercontent.com") or host.endswith(
        ".github.com"
    )


def _github_to_raw(url: str) -> str:
    """Convert github.com blob URLs to raw.githubusercontent.com for clean content.

    e.g. https://github.com/org/repo/blob/main/README.md
      -> https://raw.githubusercontent.com/org/repo/main/README.md
    """
    parsed = urlparse(url)
    if parsed.netloc.lower() != "github.com":
        return url

    m = re.match(r"^/([^/]+/[^/]+)/blob/(.+)$", parsed.path)
    if m:
        return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}"
    return url


def fetch_external_url(url: str, gh_token: str = "") -> PageData | None:
    """Fetch an external URL (follow redirects, 1 level only).

    Args:
        url: The URL to fetch.
        gh_token: Optional GitHub token for private repo access.
    """
    headers: dict[str, str] = {}
    fetch_url = url

    if _is_github_url(url) and gh_token:
        headers["Authorization"] = f"token {gh_token}"
        fetch_url = _github_to_raw(url)

    try:
        with httpx.Client(
            timeout=15.0, follow_redirects=True, max_redirects=5, headers=headers
        ) as client:
            resp = client.get(fetch_url)
            resp.raise_for_status()

            content_type = resp.headers.get("content-type", "")

            # Raw GitHub content is served as text/plain for markdown etc.
            is_raw_gh = "raw.githubusercontent.com" in str(resp.url)

            if (
                not is_raw_gh
                and "html" not in content_type
                and "text" not in content_type
            ):
                print(
                    f"[INFO] Skipping non-text URL: {url} ({content_type})",
                    file=sys.stderr,
                )
                return None

            if is_raw_gh and ("text/plain" in content_type):
                # Already markdown/text — use as-is
                md = resp.text
            else:
                from markdownify import markdownify

                md = markdownify(resp.text, heading_style="ATX", bullets="-")

            md = re.sub(r"\n{3,}", "\n\n", md).strip()

            # Truncate very large pages
            if len(md) > 50000:
                md = md[:50000] + "\n\n... (truncated)"

            now = datetime.now(timezone.utc).isoformat()
            parsed = urlparse(str(resp.url))  # use final URL after redirects
            title = (
                _extract_html_title(resp.text) if "html" in content_type else ""
            ) or parsed.netloc + parsed.path

            return PageData(
                id=f"ext:{url}",
                title=title,
                space_key="",
                path=["External"],
                web_url=url,  # keep original URL, not the raw rewrite
                markdown_content=md,
                last_modified=now,
                version_when=now,
                source_type="external",
            )
    except (httpx.HTTPError, Exception) as exc:
        print(f"[WARN] Failed to fetch external URL {url}: {exc}", file=sys.stderr)
        return None


def _extract_html_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""


# ---------------------------------------------------------------------------
# Graph-walking crawler
# ---------------------------------------------------------------------------


@dataclass
class _CrawlItem:
    """An item in the crawl queue."""

    page_id: str
    depth: int
    path: list[str]
    max_depth_override: int | None = None  # from parent's directive


class SubtreeCrawler:
    """Crawl Confluence pages by walking children + linked pages + external URLs."""

    def __init__(self, client: ConfluenceClient, config: Config):
        self._client = client
        self._config = config

    def crawl_all(self) -> list[PageData]:
        """Crawl all configured roots using BFS graph walk."""
        visited_ids: set[str] = set()
        visited_urls: set[str] = set()
        all_pages: list[PageData] = []
        queue: deque[_CrawlItem] = deque()

        # Seed the queue with root pages
        for root_id in self._config.root_page_ids:
            queue.append(_CrawlItem(page_id=root_id, depth=0, path=[]))

        while queue and len(all_pages) < self._config.max_pages:
            item = queue.popleft()

            if item.page_id in visited_ids:
                continue
            visited_ids.add(item.page_id)

            # Determine effective max depth for this item
            effective_max = item.max_depth_override or self._config.max_depth
            if item.depth > effective_max:
                continue

            # Fetch page
            try:
                raw = self._client.get_page_with_body(item.page_id)
            except httpx.HTTPStatusError as exc:
                print(
                    f"[WARN] Failed to fetch page {item.page_id}: {exc}",
                    file=sys.stderr,
                )
                continue

            body_html = raw.get("body", {}).get("storage", {}).get("value", "")
            directives = parse_directives_from_html(body_html)
            page = self._parse_page(raw, item.path)
            all_pages.append(page)

            # Determine depth limit for children/linked pages
            child_max_depth = (
                directives.max_depth
                if directives.max_depth is not None
                else effective_max
            )
            child_depth = item.depth + 1
            child_path = item.path + [page.title]

            # Queue child pages
            if child_depth <= child_max_depth:
                try:
                    children = self._client.get_child_pages(item.page_id)
                    for child in children:
                        cid = child.get("id", "")
                        if cid and cid not in visited_ids:
                            queue.append(
                                _CrawlItem(
                                    page_id=cid,
                                    depth=child_depth,
                                    path=child_path,
                                    max_depth_override=child_max_depth,
                                )
                            )
                except httpx.HTTPStatusError as exc:
                    print(
                        f"[WARN] Failed to fetch children of {item.page_id}: {exc}",
                        file=sys.stderr,
                    )

            # Queue linked Confluence pages
            if directives.follow_links:
                linked_ids = extract_confluence_page_ids(body_html)
                for lid in linked_ids:
                    if lid not in visited_ids:
                        queue.append(
                            _CrawlItem(
                                page_id=lid,
                                depth=child_depth,
                                path=child_path,
                                max_depth_override=child_max_depth,
                            )
                        )

                # Resolve pages referenced by title in macros
                # (include, excerpt-include, children)
                macro_refs = extract_macro_page_refs(body_html)
                for title, space_key in macro_refs:
                    resolved_id = self._client.find_page_by_title(title, space_key)
                    if resolved_id and resolved_id not in visited_ids:
                        queue.append(
                            _CrawlItem(
                                page_id=resolved_id,
                                depth=child_depth,
                                path=child_path,
                                max_depth_override=child_max_depth,
                            )
                        )
                    elif not resolved_id:
                        print(
                            f'[WARN] Macro references page "{title}"'
                            f"{' in ' + space_key if space_key else ''}"
                            " but it was not found",
                            file=sys.stderr,
                        )

            # Fetch external URLs (1 level, no recursion)
            if directives.follow_external:
                ext_urls = extract_external_urls(body_html, self._config.base_url)
                for url in ext_urls:
                    if (
                        url not in visited_urls
                        and len(all_pages) < self._config.max_pages
                    ):
                        visited_urls.add(url)
                        ext_page = fetch_external_url(url, self._config.gh_token)
                        if ext_page:
                            all_pages.append(ext_page)

        if len(all_pages) >= self._config.max_pages:
            print(
                f"[WARN] Reached max_pages limit ({self._config.max_pages}), stopping crawl",
                file=sys.stderr,
            )

        return all_pages[: self._config.max_pages]

    def _parse_page(self, raw: dict, path: list[str]) -> PageData:
        """Parse API response into a PageData."""
        body_storage = raw.get("body", {}).get("storage", {}).get("value", "")
        version = raw.get("version", {})
        space = raw.get("spaceId", "")

        base = self._config.base_url.rstrip("/")
        web_url = raw.get("_links", {}).get("webui", "")
        if web_url:
            web_url = base + web_url

        md = confluence_to_markdown(body_storage, base)
        md = strip_directive_block(md)

        return PageData(
            id=str(raw["id"]),
            title=raw.get("title", ""),
            space_key=space,
            path=path,
            web_url=web_url,
            markdown_content=md,
            last_modified=version.get("createdAt", ""),
            version_when=version.get("createdAt", ""),
            source_type="confluence",
        )

    def get_root_versions(self) -> dict[str, str]:
        """Fetch version.when for each root page (cheap version check)."""
        versions: dict[str, str] = {}
        for root_id in self._config.root_page_ids:
            try:
                meta = self._client.get_page_metadata(root_id)
                versions[root_id] = meta.get("version", {}).get("createdAt", "")
            except httpx.HTTPStatusError as exc:
                print(
                    f"[WARN] Failed to check version for root {root_id}: {exc}",
                    file=sys.stderr,
                )
        return versions
