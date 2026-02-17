from __future__ import annotations

import json

from result import Err, Ok

from dux.config.loader import load_config, sample_config_json
from tests.fs_mock import MemoryFileSystem


class TestLoadConfig:
    def test_valid_json_dict(self) -> None:
        fs = MemoryFileSystem()
        fs.add_file("/mock/home/.config/dux/config.json", content=json.dumps({"scanWorkers": 2}))
        result = load_config(fs=fs)
        assert isinstance(result, Ok)
        assert result.unwrap().scan_workers == 2

    def test_non_dict_json_returns_err(self) -> None:
        fs = MemoryFileSystem()
        fs.add_file("/mock/home/.config/dux/config.json", content=json.dumps([1, 2, 3]))
        result = load_config(fs=fs)
        assert isinstance(result, Err)
        assert "must be a JSON object" in result.unwrap_err()

    def test_sample_config_json_is_valid(self) -> None:
        raw = sample_config_json()
        parsed = json.loads(raw)
        assert isinstance(parsed, dict)
        assert "patterns" in parsed

    def test_custom_path(self) -> None:
        fs = MemoryFileSystem()
        fs.add_file("/custom/config.json", content=json.dumps({"topCount": 5}))
        result = load_config(path="/custom/config.json", fs=fs)
        assert isinstance(result, Ok)
        assert result.unwrap().top_count == 5
