from __future__ import annotations

import json
from pathlib import Path

from diskanalysis.config.defaults import default_config
from diskanalysis.config.schema import AppConfig, from_dict

CONFIG_PATH = Path("~/.config/diskanalysis/config.json").expanduser()


def load_config(path: Path | None = None) -> tuple[AppConfig, str | None]:
    resolved = path or CONFIG_PATH
    if not resolved.exists():
        return default_config(), None

    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return default_config(), f"Config at {resolved} must be a JSON object. Using defaults."
        return from_dict(payload, default_config()), None
    except Exception as exc:  # noqa: BLE001
        return default_config(), f"Failed reading config at {resolved}: {exc}. Using defaults."


def sample_config_json() -> str:
    return json.dumps(default_config().to_dict(), indent=2)
