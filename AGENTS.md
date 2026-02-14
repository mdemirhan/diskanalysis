# Repository Agent Preferences

## Tooling

- Use `uv` for all operations:
  - `uv sync` to install dependencies
  - `uv run <command>` to run commands in the project environment
  - `uv add <package>` to add dependencies
- Use `ruff` for linting and formatting (`ruff check`, `ruff format`)
- Use `basedpyright` for type checking
- Use `pytest` for testing
- After making code changes, run `uv run ruff format` and `uv run basedpyright` before considering work complete

## Error Handling Style

- Use the `result` library (`Result`, `Ok`, `Err`) for operation outcomes.
- Follow a pragmatic style:
  - Keep pure/service functions returning `Result` for expected failure paths.
  - Keep boundary layers (CLI/TUI) imperative and explicit.

## Migration Guidance

- Avoid tuple-based `(value, warning/error)` return patterns for new code.
- Avoid custom ad-hoc success/failure unions for operation results when `Result` is appropriate.
- Keep user-facing behavior unchanged when refactoring to `Result`.
