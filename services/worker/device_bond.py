"""Explicit local-device resource consent for NEXORA.

The bond is a local policy record only: it never starts background work. A
job runner must check enabled=True and honour the selected ceilings before it
allocates device resources.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_LIMIT = 70
MIN_LIMIT = 50
MAX_LIMIT = 90


def _bond_path(data_root: str | Path) -> Path:
    root = Path(data_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root / "device-access-bond.json"


def default_bond() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "enabled": False,
        "consented_at": None,
        "limits": {
            "cpu_percent": DEFAULT_LIMIT,
            "ram_percent": DEFAULT_LIMIT,
            "gpu_percent": DEFAULT_LIMIT,
        },
        "policy": "resources_may_be_used_only_while_a_creator_started_job_is_running",
    }


def load_bond(data_root: str | Path) -> dict[str, Any]:
    path = _bond_path(data_root)
    if not path.is_file():
        return default_bond()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # A corrupt policy must never be interpreted as consent.
        return default_bond()
    if not isinstance(data, dict) or data.get("schema_version") != "1.0":
        return default_bond()
    defaults = default_bond()
    limits = data.get("limits") if isinstance(data.get("limits"), dict) else {}
    defaults.update({key: data.get(key, defaults[key]) for key in ("enabled", "consented_at")})
    defaults["enabled"] = defaults["enabled"] is True
    defaults["limits"] = {
        name: _bounded_limit(limits.get(name, DEFAULT_LIMIT))
        for name in ("cpu_percent", "ram_percent", "gpu_percent")
    }
    return defaults


def _bounded_limit(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("Resource limits must be whole percentages.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Resource limits must be whole percentages.") from exc
    if parsed < MIN_LIMIT or parsed > MAX_LIMIT:
        raise ValueError(f"Resource limits must be between {MIN_LIMIT}% and {MAX_LIMIT}%.")
    return parsed


def save_bond(
    data_root: str | Path,
    *,
    enabled: bool,
    cpu_percent: int = DEFAULT_LIMIT,
    ram_percent: int = DEFAULT_LIMIT,
    gpu_percent: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    if not isinstance(enabled, bool):
        raise ValueError("Explicit enabled consent is required.")
    limits = {
        "cpu_percent": _bounded_limit(cpu_percent),
        "ram_percent": _bounded_limit(ram_percent),
        "gpu_percent": _bounded_limit(gpu_percent),
    }
    from datetime import datetime, timezone

    record = {
        "schema_version": "1.0",
        "enabled": enabled,
        "consented_at": datetime.now(timezone.utc).isoformat() if enabled else None,
        "limits": limits,
        "policy": "resources_may_be_used_only_while_a_creator_started_job_is_running",
    }
    path = _bond_path(data_root)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, indent=2), encoding="utf-8")
    os.replace(temporary, path)
    return record
