from __future__ import annotations

from pathlib import Path

from result import Err, Ok

from diskanalysis.config.loader import load_config


def test_load_config_missing_uses_defaults(tmp_path: Path) -> None:
    result = load_config(tmp_path / "missing.json")
    assert isinstance(result, Ok)
    cfg = result.unwrap()
    assert cfg.temp_patterns


def test_load_config_invalid_returns_warning(tmp_path: Path) -> None:
    p = tmp_path / "config.json"
    p.write_text("not-json", encoding="utf-8")

    result = load_config(p)
    assert isinstance(result, Err)
    warning = result.unwrap_err()
    assert "failed reading config" in warning.lower()
