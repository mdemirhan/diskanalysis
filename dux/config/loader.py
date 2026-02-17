from __future__ import annotations

import json

from result import Err, Ok, Result

from dux.config.defaults import default_config
from dux.config.schema import AppConfig
from dux.services.fs import DEFAULT_FS, FileSystem

CONFIG_PATH = "~/.config/dux/config.json"


def load_config(path: str | None = None, fs: FileSystem = DEFAULT_FS) -> Result[AppConfig, str]:
    resolved = fs.expanduser(path or CONFIG_PATH)
    if not fs.exists(resolved):
        return Ok(default_config())

    try:
        payload = json.loads(fs.read_text(resolved))
        if not isinstance(payload, dict):
            return Err(f"Config at {resolved} must be a JSON object.")
        return Ok(AppConfig.from_dict(payload, default_config()))
    except Exception as exc:  # noqa: BLE001
        return Err(f"Failed reading config at {resolved}: {exc}.")


def sample_config_json() -> str:
    return json.dumps(default_config().to_dict(), indent=2)
