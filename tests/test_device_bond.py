from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.worker.device_bond import default_bond, load_bond, save_bond


def test_device_bond_defaults_to_no_consent(tmp_path: Path) -> None:
    bond = load_bond(tmp_path)
    assert bond["enabled"] is False
    assert bond["consented_at"] is None
    assert bond["limits"]["cpu_percent"] == 70
    assert not (tmp_path / "device-access-bond.json").exists()


def test_device_bond_requires_explicit_consent_and_persists_limits(tmp_path: Path) -> None:
    bond = save_bond(
        tmp_path,
        enabled=True,
        cpu_percent=60,
        ram_percent=75,
        gpu_percent=85,
    )
    assert bond["enabled"] is True
    assert bond["limits"] == {
        "cpu_percent": 60,
        "ram_percent": 75,
        "gpu_percent": 85,
    }
    assert load_bond(tmp_path) == bond


def test_device_bond_revocation_clears_consent(tmp_path: Path) -> None:
    save_bond(tmp_path, enabled=True)
    revoked = save_bond(tmp_path, enabled=False)
    assert revoked["enabled"] is False
    assert revoked["consented_at"] is None
    assert load_bond(tmp_path)["enabled"] is False


@pytest.mark.parametrize("value", [49, 91, -1, "high", True])
def test_device_bond_rejects_unsafe_or_invalid_limits(tmp_path: Path, value) -> None:
    with pytest.raises(ValueError):
        save_bond(tmp_path, enabled=True, cpu_percent=value)


def test_corrupt_device_bond_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "device-access-bond.json").write_text("{not-json", encoding="utf-8")
    assert load_bond(tmp_path) == default_bond()
