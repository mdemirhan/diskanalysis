# Repository Agent Preferences

## Error Handling Style
- Use the `result` library (`Result`, `Ok`, `Err`) for operation outcomes.
- Follow a pragmatic style:
  - Keep pure/service functions returning `Result` for expected failure paths.
  - Keep boundary layers (CLI/TUI) imperative and explicit.
## Migration Guidance
- Avoid tuple-based `(value, warning/error)` return patterns for new code.
- Avoid custom ad-hoc success/failure unions for operation results when `Result` is appropriate.
- Keep user-facing behavior unchanged when refactoring to `Result`.
