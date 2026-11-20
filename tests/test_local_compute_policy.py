from core.execution_policy import is_local_compute_only_request, local_compute_block_payload
from services.worker.local_security import PairingAuthority
from services.worker.system_profile import check_requirements


def test_cloud_compute_routes_are_local_only():
    assert is_local_compute_only_request("POST", "/api/projects/demo/generate")
    assert is_local_compute_only_request("POST", "/api/v1/workspace/projects/demo/jobs")
    assert is_local_compute_only_request(
        "POST", "/api/v1/workspace/projects/demo/assets/asset-1/convert"
    )
    assert is_local_compute_only_request(
        "POST", "/api/v1/workspace/projects/demo/creator-workflow/gameplay/compile"
    )


def test_cloud_control_plane_routes_remain_available():
    assert not is_local_compute_only_request("GET", "/api/projects")
    assert not is_local_compute_only_request("GET", "/health")
    assert not is_local_compute_only_request(
        "POST", "/api/v1/creator-flow/checkout"
    )
    assert not is_local_compute_only_request(
        "PUT", "/api/v1/workspace/projects/demo"
    )


def test_local_compute_block_response_is_machine_readable():
    payload = local_compute_block_payload()
    assert payload["detail"]["code"] == "LOCAL_COMPUTE_REQUIRED"
    assert "creator's paired" in payload["detail"]["message"]


def test_pairing_code_is_one_time_and_token_is_revocable():
    authority = PairingAuthority("12345678")
    token, expires_at = authority.exchange("12345678")
    assert expires_at > 0
    assert authority.resolve(token) is not None
    try:
        authority.exchange("12345678")
        assert False, "pairing code must only be exchanged once"
    except ValueError:
        pass
    assert authority.revoke(token) is True
    assert authority.resolve(token) is None


def test_pairing_rejects_wrong_code_without_consuming_valid_code():
    authority = PairingAuthority("87654321")
    try:
        authority.exchange("00000000")
        assert False, "wrong pairing code should fail"
    except ValueError:
        pass
    token, _ = authority.exchange("87654321")
    assert authority.resolve(token) is not None


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
            "disk_free_gib": 80,
        },
        "gpu": {
            "primary": {
                "vendor": "NVIDIA",
                "memory_total_bytes": 8 * 1024**3,
            }
        },
        "tools": {"blender": {"available": True}, "python": {"available": True}},
    }
    result = check_requirements("image_to_3d", profile)
    assert result["ready"] is True
