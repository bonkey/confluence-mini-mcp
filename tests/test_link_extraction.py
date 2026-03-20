"""Test link extraction from Confluence storage format."""

from confluence_mini_mcp.crawler import (
    extract_confluence_page_ids,
    extract_external_urls,
    extract_macro_page_refs,
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


def test_extract_macro_page_refs():
    html = """
    <ac:structured-macro ac:name="include">
      <ac:parameter ac:name="">
        <ac:link><ri:page ri:content-title="API Design" ri:space-key="ENG" /></ac:link>
      </ac:parameter>
    </ac:structured-macro>
    <ac:structured-macro ac:name="excerpt-include">
      <ac:parameter ac:name="">
        <ac:link><ri:page ri:content-title="Status Page" /></ac:link>
      </ac:parameter>
    </ac:structured-macro>
    <ac:structured-macro ac:name="children">
      <ac:parameter ac:name="page">
        <ac:link><ri:page ri:content-title="Project Hub" ri:space-key="TEAM" /></ac:link>
      </ac:parameter>
    </ac:structured-macro>
    """
    refs = extract_macro_page_refs(html)
    assert ("API Design", "ENG") in refs
    assert ("Status Page", "") in refs
    assert ("Project Hub", "TEAM") in refs
    assert len(refs) == 3
    print("test_extract_macro_page_refs passed")


def test_extract_macro_page_refs_empty():
    html = '<ac:structured-macro ac:name="code"><ac:plain-text-body>x</ac:plain-text-body></ac:structured-macro>'
    assert extract_macro_page_refs(html) == []
    print("test_extract_macro_page_refs_empty passed")


if __name__ == "__main__":
    test_extract_page_ids()
    test_extract_external_urls()
    test_no_links()
    test_extract_macro_page_refs()
    test_extract_macro_page_refs_empty()
    print("All link extraction tests passed")
