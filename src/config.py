from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path).resolve()
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    config["_config_path"] = str(config_path)
    config["_base_dir"] = str(config_path.parent)
    validate_config(config)
    return config


def save_config(config: dict[str, Any], path: str | Path | None = None) -> None:
    target = Path(path or config["_config_path"]).resolve()
    serializable = deepcopy(config)
    serializable.pop("_config_path", None)
    serializable.pop("_base_dir", None)
    with target.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(serializable, handle, sort_keys=False)


def resolve_path(config: dict[str, Any], value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else Path(config["_base_dir"]) / path


def validate_config(config: dict[str, Any]) -> None:
    required = ("camera", "roi", "counting_line", "detection", "tracking", "color_detection", "storage")
    missing = [key for key in required if key not in config]
    if missing:
        raise ValueError(f"Missing configuration sections: {', '.join(missing)}")
    roi = config["roi"]
    for key in ("x", "y", "width", "height"):
        value = float(roi[key])
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"roi.{key} must be between 0 and 1")
    if roi["width"] <= 0 or roi["height"] <= 0:
        raise ValueError("ROI width and height must be positive")
    direction = config["counting_line"].get("direction", "any")
    if direction not in {"any", "up", "down"}:
        raise ValueError("counting_line.direction must be any, up, or down")
