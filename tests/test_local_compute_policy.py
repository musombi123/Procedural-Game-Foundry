import pytest
from core.execution_policy import is_local_compute_only_request, local_compute_block_payload
from services.worker.local_security import PairingAuthority
from services.worker.system_profile import check_requirements


def test_cloud_compute_routes_are_local_only():
    assert is_local_compute_only_request("POST", "/api/projects/demo/generate")
    assert is_local_compute_only_request("POST", "/api/projects/demo/assets")
    assert is_local_compute_only_request("POST", "/api/v1/workspace/projects/demo/jobs")
    assert is_local_compute_only_request(
        "POST", "/api/v1/workspace/projects/demo/assets/asset-1/convert"
    )
    assert is_local_compute_only_request(
        "POST", "/api/v1/workspace/projects/demo/creator-workflow/gameplay/compile"
    )


def test_cloud_control_plane_routes_remain_available():
    assert not is_local_compute_only_request("GET", "/health")
    assert not is_local_compute_only_request("GET", "/api/capabilities")
    assert not is_local_compute_only_request(
        "POST", "/api/v1/creator-flow/checkout"
    )
    assert not is_local_compute_only_request(
        "GET", "/api/v1/creator-flow/plans"
    )


def test_all_project_and_workspace_data_is_local_only():
    assert is_local_compute_only_request("GET", "/api/projects")
    assert is_local_compute_only_request("GET", "/api/projects/demo")
    assert is_local_compute_only_request("PUT", "/api/projects/demo/world")
    assert is_local_compute_only_request("GET", "/api/v1/workspace/projects")
    assert is_local_compute_only_request("PATCH", "/api/v1/workspace/projects/demo")
    assert is_local_compute_only_request("GET", "/api/v1/workspace/jobs/job-1/artifacts")
    assert is_local_compute_only_request("GET", "/api/v1/studio/templates")
    assert is_local_compute_only_request("GET", "/api/v1/workspace/assets/conversion-capabilities")


def test_local_compute_block_response_is_machine_readable():
    payload = local_compute_block_payload()
    assert payload["detail"]["code"] == "LOCAL_COMPUTE_REQUIRED"
    assert "creator's paired" in payload["detail"]["message"]


def test_pairing_issues_verified_account_session_and_token_is_revocable():
    authority = PairingAuthority()
    cloud_token = "verified-cloud-session-" + ("x" * 32)
    token, expires_at = authority.issue("creator-123", cloud_token)

    assert expires_at > 0
    principal = authority.resolve(token)
    assert principal is not None
    assert principal.user_id == "creator-123"
    assert principal.cloud_access_token == cloud_token
    assert authority.revoke(token) is True
    assert authority.resolve(token) is None


def test_pairing_authority_rejects_missing_verified_account_material():
    authority = PairingAuthority()

    with pytest.raises(ValueError):
        authority.issue("", "verified-cloud-session-" + ("x" * 32))

    with pytest.raises(ValueError):
        authority.issue("creator-123", "short")


def test_2d_profile_does_not_require_a_dedicated_gpu():
    profile = {
        "machine": {
            "logical_cpu_count": 4,
            "ram_total_gib": 8,
            "disk_free_gib": 20,
        },
        "gpu": {"primary": None},
        "tools": {"godot": {"available": True}},
    }
    result = check_requirements("editor_2d", profile)
    assert result["ready"] is True
    assert all(item["name"] != "CUDA GPU" for item in result["checks"])


def test_image_to_3d_profile_requires_cuda_vram():
    profile = {
        "machine": {
            "logical_cpu_count": 8,
            "ram_total_gib": 32,
            "ram_available_gib": 12,
            "disk_free_gib": 80,
        },
        "gpu": {
            "primary": {
                "vendor": "NVIDIA",
                "memory_total_bytes": 8 * 1024**3,
                "memory_free_bytes": 5 * 1024**3,
            }
        },
        "tools": {"blender": {"available": True}, "python": {"available": True}},
        "workers": {"triposr": {"available": True}},
    }
    result = check_requirements("image_to_3d", profile)
    assert result["ready"] is True


def test_image_to_3d_is_blocked_when_gpu_vram_is_busy():
    profile = {
        "machine": {
            "logical_cpu_count": 8,
            "ram_total_gib": 32,
            "ram_available_gib": 12,
            "disk_free_gib": 80,
        },
        "gpu": {
            "primary": {
                "vendor": "NVIDIA",
                "memory_total_bytes": 8 * 1024**3,
                "memory_free_bytes": 1 * 1024**3,
            }
        },
        "tools": {"blender": {"available": True}, "python": {"available": True}},
        "workers": {"triposr": {"available": True}},
    }
    result = check_requirements("image_to_3d", profile)
    assert result["ready"] is False
    assert any(
        item["name"] == "Available GPU memory" and item["status"] == "fail"
        for item in result["checks"]
    )



def test_local_workload_requires_device_access_bond(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from services.worker.workload_guard import require_device_profile

    monkeypatch.setenv("NEXORA_LOCAL_AGENT", "true")
    monkeypatch.setenv("NEXORA_LOCAL_AGENT_DATA", str(tmp_path))
    with pytest.raises(HTTPException) as error:
        require_device_profile("editor_2d")
    assert error.value.status_code == 403
    assert error.value.detail["code"] == "DEVICE_ACCESS_BOND_REQUIRED"


def test_enabled_device_bond_is_attached_to_local_preflight(tmp_path, monkeypatch):
    from services.worker.device_bond import save_bond
    import services.worker.workload_guard as guard

    monkeypatch.setenv("NEXORA_LOCAL_AGENT", "true")
    monkeypatch.setenv("NEXORA_LOCAL_AGENT_DATA", str(tmp_path))
    save_bond(tmp_path, enabled=True, cpu_percent=60, ram_percent=65, gpu_percent=70)
    monkeypatch.setattr(guard, "collect_system_profile", lambda: {
        "machine": {"logical_cpu_count": 4, "ram_total_gib": 8, "disk_free_gib": 20},
        "gpu": {"primary": None},
        "tools": {"godot": {"available": True}},
    })
    result = guard.require_device_profile("editor_2d")
    assert result["device_access_bond"]["enabled"] is True
    assert result["device_access_bond"]["limits"]["cpu_percent"] == 60


def test_procedural_3d_is_blocked_when_cpu_is_busy_even_with_enough_total_cores():
    profile = {
        "machine": {
            "logical_cpu_count": 8,
            "cpu_utilization_percent": 90.0,
            "cpu_available_cores": 0.8,
            "ram_total_gib": 32,
            "ram_available_gib": 16,
            "disk_free_gib": 100,
        },
        "gpu": {"primary": None},
        "tools": {
            "blender": {"available": True},
            "godot": {"available": True},
        },
    }

    result = check_requirements("procedural_3d", profile)

    assert result["ready"] is False
    cpu_check = next(item for item in result["checks"] if item["name"] == "Available CPU capacity")
    assert cpu_check["status"] == "fail"
    assert "90%" in cpu_check["detail"]


def test_procedural_3d_passes_cpu_preflight_when_live_headroom_is_sufficient():
    profile = {
        "machine": {
            "logical_cpu_count": 8,
            "cpu_utilization_percent": 40.0,
            "cpu_available_cores": 4.8,
            "ram_total_gib": 32,
            "ram_available_gib": 16,
            "disk_free_gib": 100,
        },
        "gpu": {"primary": None},
        "tools": {
            "blender": {"available": True},
            "godot": {"available": True},
        },
    }

    result = check_requirements("procedural_3d", profile)

    assert result["ready"] is True
    cpu_check = next(item for item in result["checks"] if item["name"] == "Available CPU capacity")
    assert cpu_check["status"] == "pass"
