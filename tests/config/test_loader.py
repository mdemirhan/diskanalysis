from __future__ import annotations

from pathlib import Path

from diskanalysis.config.loader import load_config


def test_load_config_missing_uses_defaults(tmp_path: Path) -> None:
    cfg, warning = load_config(tmp_path / "missing.json")
    assert warning is None
    assert cfg.temp_patterns


def test_load_config_invalid_returns_warning(tmp_path: Path) -> None:
    p = tmp_path / "config.json"
    p.write_text("not-json", encoding="utf-8")

    cfg, warning = load_config(p)
    assert cfg.cache_patterns
    assert warning is not None
