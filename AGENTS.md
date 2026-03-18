# Agent rules

All common tasks are in the `Justfile`. Use `just <task>` to run them.

## Testing

Always test after making changes: `just test`

## Formatting

Format all Python code with black before committing: `just fmt`

Run both: `just check`

## Documentation

Keep README.md up to date when adding or changing tools, config options, or usage patterns.

## Versioning & releases

Version lives in one place: `pyproject.toml` → `version`. Use semver (0.x.y for now).

Bump the version when making a release-worthy change. To release: `just release`

This tags the commit and pushes. Users install from git via `uvx --from git+...` and can pin to a tag.
