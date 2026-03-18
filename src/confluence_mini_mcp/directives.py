"""Parse confluence-mcp directives from Confluence page content.

Users add a directive block anywhere on the page (paragraph, table cell,
panel body — anywhere text can go). The format is:

    [confluence-mcp]
    max_depth=3
    follow_links=false
    follow_external=true

The block starts with a line containing exactly "[confluence-mcp]" and
continues until the next blank line or end of content. In storage-format
HTML this is just plain text, so it works in any Confluence editor
without needing macros.

The directive block is stripped from the Markdown output so agents
don't see it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class PageDirectives:
    max_depth: int | None = None  # override crawl depth from this page down
    follow_links: bool = True  # whether to follow linked Confluence pages
    follow_external: bool = True  # whether to fetch external HTTP links


# Matches [confluence-mcp] followed by key=value lines until blank line or end
_DIRECTIVE_RE = re.compile(
    r"\[confluence-mcp\]\s*\n((?:[^\n]+\n?)*)",
    re.IGNORECASE,
)


def parse_directives_from_html(html: str) -> PageDirectives:
    """Extract directives from storage-format HTML (searches raw text)."""
    # Strip HTML tags to get plain text for matching
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&\w+;", " ", text)  # decode entities roughly
    return _parse_from_text(text)


def parse_directives_from_markdown(md: str) -> PageDirectives:
    """Extract directives from Markdown content."""
    return _parse_from_text(md)


def strip_directive_block(md: str) -> str:
    """Remove the [confluence-mcp] block from Markdown so agents don't see it."""
    return _DIRECTIVE_RE.sub("", md).strip()


def _parse_from_text(text: str) -> PageDirectives:
    directives = PageDirectives()

    match = _DIRECTIVE_RE.search(text)
    if not match:
        return directives

    body = match.group(1)
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            break  # blank line or comment ends the block
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().lower()
        value = value.strip().lower()

        if key == "max_depth":
            try:
                directives.max_depth = int(value)
            except ValueError:
                pass
        elif key == "follow_links":
            directives.follow_links = value in ("true", "1", "yes")
        elif key == "follow_external":
            directives.follow_external = value in ("true", "1", "yes")

    return directives
