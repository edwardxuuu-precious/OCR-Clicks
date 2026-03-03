from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT_DIR / "VERSION.json"

DEFAULT_VERSION_INFO: dict[str, Any] = {
    "version": "0.0.0",
    "label": "v0.0.0",
    "version_date": "1970-01-01",
    "version_index": 0,
    "released_at": "1970-01-01T00:00:00+00:00",
    "source_commit": "",
}


def _safe_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except Exception:
        return fallback


@lru_cache(maxsize=1)
def load_project_version() -> dict[str, Any]:
    info = dict(DEFAULT_VERSION_INFO)
    if not VERSION_FILE.exists():
        return info

    try:
        raw = json.loads(VERSION_FILE.read_text(encoding="utf-8"))
    except Exception:
        return info

    if isinstance(raw, dict):
        info.update(raw)

    version = str(info.get("version", DEFAULT_VERSION_INFO["version"])).strip() or DEFAULT_VERSION_INFO["version"]
    version_date = str(info.get("version_date", DEFAULT_VERSION_INFO["version_date"])).strip()
    version_index = _safe_int(info.get("version_index"), 0)
    released_at = str(info.get("released_at", DEFAULT_VERSION_INFO["released_at"])).strip()
    source_commit = str(info.get("source_commit", "")).strip()
    label = str(info.get("label", "")).strip() or f"v{version}"

    info["version"] = version
    info["label"] = label
    info["version_date"] = version_date
    info["version_index"] = version_index
    info["released_at"] = released_at
    info["source_commit"] = source_commit
    return info


PROJECT_VERSION_INFO = load_project_version()
PROJECT_VERSION = str(PROJECT_VERSION_INFO["version"])
PROJECT_VERSION_LABEL = str(PROJECT_VERSION_INFO["label"])
PROJECT_VERSION_DATE = str(PROJECT_VERSION_INFO["version_date"])
PROJECT_VERSION_INDEX = int(PROJECT_VERSION_INFO["version_index"])
PROJECT_RELEASED_AT = str(PROJECT_VERSION_INFO["released_at"])
PROJECT_SOURCE_COMMIT = str(PROJECT_VERSION_INFO["source_commit"])

