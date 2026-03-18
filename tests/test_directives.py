"""Test directive parsing and stripping."""

from confluence_mini_mcp.directives import (
    parse_directives_from_html,
    parse_directives_from_markdown,
    strip_directive_block,
)


def test_parse_from_html():
    html = """
    <p>Some content</p>
    <p>[confluence-mcp]
    max_depth=3
    follow_links=false
    follow_external=true
    </p>
    <p>More content</p>
    """
    d = parse_directives_from_html(html)
    assert d.max_depth == 3
    assert d.follow_links is False
    assert d.follow_external is True
    print("test_parse_from_html passed")


def test_parse_from_markdown():
    md = """# My Page

Some intro text.

[confluence-mcp]
max_depth=5
follow_links=true
follow_external=false

## Rest of the page
"""
    d = parse_directives_from_markdown(md)
    assert d.max_depth == 5
    assert d.follow_links is True
    assert d.follow_external is False
    print("test_parse_from_markdown passed")


def test_no_directives():
    d = parse_directives_from_markdown("# Just a normal page\n\nNo directives here.")
    assert d.max_depth is None
    assert d.follow_links is True
    assert d.follow_external is True
    print("test_no_directives passed")


def test_strip_directive_block():
    md = """# My Page

Some intro.

[confluence-mcp]
max_depth=3
follow_links=false

## Content after
"""
    result = strip_directive_block(md)
    assert "[confluence-mcp]" not in result
    assert "max_depth" not in result
    assert "# My Page" in result
    assert "## Content after" in result
    print("test_strip_directive_block passed")


if __name__ == "__main__":
    test_parse_from_html()
    test_parse_from_markdown()
    test_no_directives()
    test_strip_directive_block()
    print("All directive tests passed")
