# confluence-mini-mcp tasks

# Run server in dry-run mode
dev:
    CONFLUENCE_DRY_RUN=true uv run python -m confluence_mini_mcp

# Format code
fmt:
    uvx black src/ tests/

# Run all tests
test:
    uv run python tests/test_directives.py
    uv run python tests/test_link_extraction.py
    CONFLUENCE_DRY_RUN=true uv run python tests/test_tools.py

# Validate config, connectivity, and cache health
doctor:
    uv run python -m confluence_mini_mcp doctor

# Format + test
check: fmt test

# Tag and push a release (reads version from pyproject.toml)
release: check
    #!/usr/bin/env bash
    version=$(uv run python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
    echo "Releasing v${version}"
    git tag "v${version}"
    git push && git push --tags
