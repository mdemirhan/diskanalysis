from __future__ import annotations

import json
from pathlib import Path

from result import Err, Ok, Result

from diskanalysis.config.defaults import default_config
from diskanalysis.config.schema import AppConfig, from_dict

CONFIG_PATH = Path("~/.config/diskanalysis/config.json").expanduser()


def load_config(path: Path | None = None) -> Result[AppConfig, str]:
    resolved = path or CONFIG_PATH
    if not resolved.exists():
        return Ok(default_config())

    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return Err(f"Config at {resolved} must be a JSON object.")
        return Ok(from_dict(payload, default_config()))
    except Exception as exc:  # noqa: BLE001
        return Err(f"Failed reading config at {resolved}: {exc}.")


def sample_config_json() -> str:
    return json.dumps(default_config().to_dict(), indent=2)
