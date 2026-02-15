# Agent Guidelines

Instructions for AI agents working on this codebase.

## Tooling

- Use `uv` for all operations:
  - `uv sync` to install dependencies
  - `uv run <command>` to run commands in the project environment
  - `uv add <package>` to add dependencies
- Use `ruff` for linting and formatting (`ruff check`, `ruff format`)
- Use `basedpyright` for type checking
- Use `pytest` for testing
- After making code changes, run `uv run ruff format`, `uv run ruff check`, and `uv run basedpyright` before considering work complete

## Architecture

```
dux/
├── cli/app.py              # Entry point, CLI flags, progress display
├── ui/
│   ├── app.py              # TUI application (Textual), all views and keybindings
│   └── app.tcss            # Textual CSS styling (Tomorrow Night theme)
├── models/
│   ├── enums.py            # NodeKind (FILE/DIRECTORY), InsightCategory (TEMP/CACHE/BUILD_ARTIFACT)
│   ├── scan.py             # ScanNode, ScanStats, ScanSnapshot, ScanError, ScanResult
│   └── insight.py          # Insight, InsightBundle dataclasses
├── config/
│   ├── schema.py           # AppConfig, PatternRule dataclasses with to_dict/from_dict
│   ├── defaults.py         # 670+ built-in pattern rules
│   └── loader.py           # JSON config loading with FileSystem abstraction
└── services/
    ├── fs.py               # FileSystem protocol, OsFileSystem, DEFAULT_FS singleton
    ├── scanner.py           # Parallel directory scanner (thread pool + queue)
    ├── insights.py          # Pattern matching, per-category min-heaps for top-K
    ├── patterns.py          # Compiled matchers: EXACT, CONTAINS, ENDSWITH, STARTSWITH, GLOB
    ├── tree.py              # Tree traversal: iter_nodes, top_nodes (heapq.nlargest)
    ├── formatting.py        # format_bytes, format_timestamp, relative_bar
    └── summary.py           # Non-interactive CLI summary rendering
```

### Data Flow

1. `cli/app.py` parses CLI args, loads config via `loader.py`, starts scan
2. `scanner.py` walks the filesystem via `FileSystem` protocol, builds `ScanSnapshot` (immutable tree of `ScanNode`)
3. `insights.py` walks the scan tree, matches against compiled patterns, produces `InsightBundle`
4. Either `summary.py` renders CLI output, or `ui/app.py` launches the interactive TUI

### Key Design Decisions

- **`ScanSnapshot` is immutable after scanning.** The scan tree never changes. All TUI views are read-only projections. Row caches are safe to keep across tab switches.
- **`Result[T, E]` for error handling.** Scanner and config loader return `Result` types. CLI/TUI boundary code unwraps them.
- **`FileSystem` protocol for testability.** Scanner and config loader accept a `fs` parameter (defaults to `DEFAULT_FS` singleton). Tests use `MemoryFileSystem` — no temp files, no disk I/O.
- **`DirEntry.stat` is bundled, not separate.** `OsFileSystem.scandir` calls `entry.stat(follow_symlinks=False)` on the `os.DirEntry` object (which uses OS-cached stat data) and bundles the result into each `DirEntry`. The scanner reads `entry.stat` directly — never calls `fs.stat()` per entry in the hot loop.

## Performance-Critical Code

**Any change to `scanner.py` or `fs.py` that could affect scanning performance must be flagged to the user before implementation.**

Key constraints:

- **Use `os.DirEntry.stat()` for cached stat.** The OS caches stat info from `readdir`/`getdents` syscalls. Calling `os.stat(path)` separately per file is an extra syscall per entry — a major regression at millions of files.
- **`scandir` uses a generator (yield).** cProfile exaggerates generator overhead due to per-call instrumentation. Real-world wall-clock benchmarks show generators are ~4% faster than list materialization (avoid per-directory list allocation). Always benchmark with `time.perf_counter`, not cProfile, for wall-clock comparisons.
- **Avoid `Path` object creation in hot loops.** The `FileSystem` protocol uses `str` for all paths. `Path` objects are only created inside `OsFileSystem` methods, never in scanner loop code.
- **`DirEntry` and `StatResult` are frozen dataclasses with `__slots__`.** Minimize per-entry allocation overhead.
- **The scan tree is I/O-bound.** On a 2.1M file scan (~22s), stat syscalls and `posix.scandir` dominate. The abstraction layer adds zero measurable overhead vs. direct `os.scandir` calls.

### Benchmarking Protocol

When evaluating performance changes:

1. Always use `time.perf_counter` for wall-clock timing, not `cProfile`
2. Run a warm-up pass first (populates OS caches)
3. Run at least 5 timed iterations and report avg + best
4. Test on both small (~300k files) and large (~2M files) directories
5. Compare against the baseline in the same session to control for I/O variance

## Error Handling

- Use the `result` library (`Result`, `Ok`, `Err`) for operation outcomes
- Keep pure/service functions returning `Result` for expected failure paths
- Keep boundary layers (CLI/TUI) imperative and explicit
- Avoid tuple-based `(value, warning)` return patterns
- Avoid custom ad-hoc success/failure unions when `Result` is appropriate

## Testing

- Tests use `MemoryFileSystem` from `tests/fs_mock.py` — no `tmp_path`, no disk I/O
- Scanner tests run with `workers=1` for deterministic ordering
- Pattern: `add_dir`/`add_file` builder methods return `self` for chaining
- `DirEntry.stat=None` simulates access errors (stat failures)
- Always run `uv run pytest -x -q` after changes

## Platform

- macOS and Linux only
- No Windows support
- Symlinks are not followed (`follow_symlinks=False` throughout)
