from __future__ import annotations

from pathlib import Path

from services.worker import managed_runtime


def test_workspace_storage_requires_both_writable_path_and_real_persistent_mount(tmp_path, monkeypatch):
    data_root = tmp_path / "nexora-compute"
    mount_root = tmp_path / "volume"
    monkeypatch.setattr(managed_runtime, "DATA_ROOT", data_root)
    monkeypatch.setattr(managed_runtime, "STORAGE_MOUNT", mount_root)
    monkeypatch.setattr(managed_runtime.os.path, "ismount", lambda path: Path(path) == mount_root)

    status = managed_runtime._workspace_storage_status()

    assert status["writable"] is True
    assert status["persistent_mount_detected"] is True
    assert status["ready"] is True
    assert status["available_gib"] > 0
    assert not list(data_root.glob(".nexora-write-check-*"))


def test_workspace_storage_does_not_claim_ephemeral_container_layer_is_persistent(tmp_path, monkeypatch):
    data_root = tmp_path / "nexora-compute"
    mount_root = tmp_path / "volume"
    monkeypatch.setattr(managed_runtime, "DATA_ROOT", data_root)
    monkeypatch.setattr(managed_runtime, "STORAGE_MOUNT", mount_root)
    monkeypatch.setattr(managed_runtime.os.path, "ismount", lambda _path: False)

    status = managed_runtime._workspace_storage_status()

    assert status["writable"] is True
    assert status["persistent_mount_detected"] is False
    assert status["ready"] is False


def test_public_server_profile_exposes_sdk_readiness_not_private_mount_path():
    profile = managed_runtime._public_profile({
        "schema_version": "1.0",
        "machine": {"logical_cpu_count": 4, "ram_total_gib": 16},
        "gpu": {"nvidia_cuda_available": False, "primary": None},
        "tools": {},
        "android": {
            "sdk_root": "/opt/android-sdk",
            "build_tools_installed": True,
            "ready_to_verify_apk": True,
        },
    })

    assert profile["android"]["sdk_configured"] is True
    assert "sdk_root" not in profile["android"]
    assert "/opt/android-sdk" not in repr(profile)
