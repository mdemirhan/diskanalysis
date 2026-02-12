# DiskAnalysis

Production-quality Python terminal disk analyzer with CLI and interactive TUI.

## Requirements

- Python 3.13+
- `uv`

## Setup

```bash
uv sync --extra dev
```

## Run

```bash
uv run diskanalysis [PATH]
uv run diskanalysis --summary [PATH]
uv run diskanalysis --temp [PATH]
uv run diskanalysis --cache [PATH]
uv run diskanalysis --temp --summary [PATH]
uv run diskanalysis --cache --summary [PATH]
uv run diskanalysis --sample-config
```

If no `PATH` is provided, the current directory is analyzed.

## Config

- Path: `~/.config/diskanalysis/config.json`
- Missing config: defaults are used silently
- Invalid config: warning is printed and defaults are used

Generate full sample config:

```bash
uv run diskanalysis --sample-config
```

Config is fully rule-driven:

- temp patterns
- cache patterns
- build artifact patterns
- custom patterns
- thresholds
- exclude paths
- additional temp/cache paths
- symlink and depth controls

## TUI Views

- `Overview`
- `Browse`
- `Insights`
- `Temp`
- `Cache`

## Keybindings

Global:

- `q` / `Ctrl+C`: quit
- `?`: help
- `Tab` / `Shift+Tab`: next/previous view
- `o`, `b`, `i`, `t`, `c`: jump to view

Browse:

- `j/k` or arrows: move
- `h/l` or left/right: collapse/expand, parent/drill-in
- `Enter`: drill in
- `Backspace`: drill out
- `Space`: toggle expand/collapse
- `gg`/`Home`: top
- `G`/`End`: bottom
- `PgUp`/`PgDn`, `Ctrl+U`/`Ctrl+D`: page

Insights/Temp/Cache lists:

- `j/k`, arrows
- `gg/G`, `Home/End`
- `PgUp/PgDn`, `Ctrl+U/Ctrl+D`

Search:

- `/`: start search
- typing updates matches live
- `n` / `N`: next/previous match
- `Enter`: finish search
- `Esc`: clear search
- `Backspace`: edit query

## Test

```bash
uv run pytest
```

## Safety

DiskAnalysis is analysis-only. It does not delete, move, or modify scanned files.
