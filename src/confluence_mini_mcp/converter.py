"""Confluence storage format (XHTML) → clean Markdown conversion."""

from __future__ import annotations

import re
from markdownify import markdownify, MarkdownConverter


class ConfluenceConverter(MarkdownConverter):
    """Custom converter that handles Confluence-specific macros."""

    def convert_ac_structured_macro(self, el, text, convert_as_inline):
        """Convert Confluence code blocks to fenced Markdown."""
        macro_name = el.get("ac:name", "")
        if macro_name == "code":
            lang = ""
            for param in el.find_all("ac:parameter"):
                if param.get("ac:name") == "language":
                    lang = param.get_text(strip=True)
            body = el.find("ac:plain-text-body") or el.find("ac:rich-text-body")
            code = body.get_text() if body else text
            return f"\n```{lang}\n{code.strip()}\n```\n"

        if macro_name in ("info", "note", "warning", "tip"):
            label = macro_name.upper()
            body = el.find("ac:rich-text-body")
            inner = self.convert(body) if body else text
            lines = inner.strip().splitlines()
            quoted = "\n".join(f"> {line}" for line in lines)
            return f"\n> **{label}:**\n{quoted}\n"

        # Fallback: just render inner text
        return text

    convert_ac_structured__macro = convert_ac_structured_macro


def confluence_to_markdown(html: str, base_url: str = "") -> str:
    """Convert Confluence storage-format HTML to Markdown.

    Args:
        html: Raw Confluence storage format XHTML.
        base_url: Base URL for resolving relative links.
    """
    if not html:
        return ""

    # Pre-process: resolve Confluence internal links
    if base_url:
        html = re.sub(
            r'<ri:page ri:content-title="([^"]*)"[^/]*/?>',
            lambda m: f'<a href="{base_url}/wiki/search?text={m.group(1)}">{m.group(1)}</a>',
            html,
        )

    result = markdownify(
        html,
        heading_style="ATX",
        bullets="-",
        strip=[
            "ac:image",
            "ac:emoticon",
            "ac:layout",
            "ac:layout-section",
            "ac:layout-cell",
        ],
        convert=["ac:structured-macro"],
    )

    # Clean up excessive blank lines
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()
