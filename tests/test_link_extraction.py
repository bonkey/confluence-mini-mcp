"""Test link extraction from Confluence storage format."""

from confluence_mini_mcp.crawler import (
    extract_confluence_page_ids,
    extract_external_urls,
)


def test_extract_page_ids():
    html = """
    <ac:link><ri:page ri:page-id="12345" /></ac:link>
    <a href="/wiki/spaces/TEAM/pages/67890/Some-Page">link</a>
    <a href="/wiki/spaces/TEAM/pages/12345/Duplicate">dup</a>
    """
    ids = extract_confluence_page_ids(html)
    assert "12345" in ids
    assert "67890" in ids
    assert len(ids) == 2  # deduped
    print("test_extract_page_ids passed")


def test_extract_external_urls():
    html = """
    <a href="https://docs.example.com/api">API Docs</a>
    <a href="https://company.atlassian.net/wiki/spaces/X/pages/1">Internal</a>
    <a href="https://github.com/org/repo">GitHub</a>
    """
    urls = extract_external_urls(html, "https://company.atlassian.net/wiki")
    assert "https://docs.example.com/api" in urls
    assert "https://github.com/org/repo" in urls
    assert len(urls) == 2  # internal link excluded
    print("test_extract_external_urls passed")


def test_no_links():
    html = "<p>Plain text, no links</p>"
    assert extract_confluence_page_ids(html) == []
    assert extract_external_urls(html, "https://x.atlassian.net/wiki") == []
    print("test_no_links passed")


if __name__ == "__main__":
    test_extract_page_ids()
    test_extract_external_urls()
    test_no_links()
    print("All link extraction tests passed")
