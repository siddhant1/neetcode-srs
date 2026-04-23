from __future__ import annotations

import json
from pathlib import Path

DEFAULTS = {
    "daily_target": 1,
}


def load(config_path: Path) -> dict:
    if not config_path.exists():
        return dict(DEFAULTS)
    try:
        data = json.loads(config_path.read_text())
    except json.JSONDecodeError:
        return dict(DEFAULTS)
    merged = dict(DEFAULTS)
    merged.update(data)
    return merged


def save(config_path: Path, config: dict) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2))


def set_key(config_path: Path, key: str, value) -> dict:
    if key not in DEFAULTS:
        raise KeyError(f"Unknown config key: {key}. Known: {list(DEFAULTS)}")
    config = load(config_path)
    config[key] = value
    save(config_path, config)
    return config
