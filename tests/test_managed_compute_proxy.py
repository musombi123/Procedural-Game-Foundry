import json

import pytest
from fastapi import HTTPException

from services.api import main as api_main


def test_local_capacity_projection_excludes_paths_device_names_and_serials():
    profile = {
        "machine": {
            "logical_cpu_count": 4,
            "cpu_utilization_percent": 37.5,
            "cpu_available_cores": 2.5,
            "ram_total_gib": 7.9,
            "ram_available_gib": 2.33,
            "disk_free_gib": 356.12,
            "disk_root": "C:\\Users\\private\\NEXORA",
            "cpu_model": "private model name",
        },
        "tools": {
            "blender": {"available": False, "path": "C:\\Private\\blender.exe", "version": None},
            "godot": {"available": True, "path": "C:\\Private\\godot.exe", "version": "4.6.1"},
        },
        "gpu": {
            "nvidia_cuda_available": True,
            "primary": {
                "vendor": "NVIDIA",
                "name": "Private GPU model",
                "memory_total_bytes": 8 * 1024**3,
                "memory_free_bytes": 6 * 1024**3,
            },
        },
        "android": {
            "sdk_root": "C:\\Users\\private\\Android\\Sdk",
            "adb": "C:\\Users\\private\\Android\\Sdk\\platform-tools\\adb.exe",
            "build_tools_installed": True,
            "ready_to_verify_apk": True,
        },
        "device_serial": "private-device-serial",
    }

    result = api_main._safe_local_compute_profile(profile)
    encoded = json.dumps(result)

    assert result["machine"]["logical_cpu_count"] == 4
    assert result["machine"]["cpu_available_cores"] == 2.5
    assert result["tools"]["blender"] == {"available": False}
    assert result["tools"]["godot"] == {"available": True}
    assert result["android"]["sdk_root"] == "configured"
    assert "C:\\Users\\private" not in encoded
    assert "Private GPU model" not in encoded
    assert "private-device-serial" not in encoded
    assert "cpu_model" not in result["machine"]


def test_managed_compute_plan_without_metrics_consent_sends_no_local_profile(monkeypatch):
    captured = {}
    monkeypatch.setenv("NEXORA_MANAGED_COMPUTE_URL", "https://compute.example.test")
    monkeypatch.setenv("NEXORA_MANAGED_COMPUTE_SECRET", "server-only-secret")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return json.dumps({
                "decision": "managed_server_candidate",
                "execution_location": "managed_server",
                "job_submission_enabled": False,
            }).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return Response()

    monkeypatch.setattr(api_main, "urlopen", fake_urlopen)
    payload = api_main.ManagedComputePlanRequest(
        workload="procedural_3d",
        local_profile={
            "machine": {"logical_cpu_count": 4, "ram_total_gib": 7.9},
            "tools": {"blender": {"available": False}},
        },
        consent_to_share_hardware_metrics=False,
    )
    result = api_main.managed_compute_plan(payload)

    assert captured["body"]["local_profile"] == {}
    assert result["local_metrics_shared"] is False
    assert result["local_metrics_policy"] == "not_shared_local_capacity_treated_as_unknown"
    assert result["execution_location"] == "managed_server"


def test_managed_compute_capabilities_degrade_cleanly_when_not_provisioned(monkeypatch):
    monkeypatch.delenv("NEXORA_MANAGED_COMPUTE_URL", raising=False)
    monkeypatch.delenv("NEXORA_MANAGED_COMPUTE_SECRET", raising=False)

    result = api_main.managed_compute_capabilities()

    assert result["available"] is False
    assert result["job_submission_enabled"] is False
    assert result["reason_code"] == "MANAGED_COMPUTE_NOT_CONFIGURED"


def test_managed_compute_proxy_uses_server_secret_and_only_safe_local_metrics(monkeypatch):
    captured = {}
    monkeypatch.setenv("NEXORA_MANAGED_COMPUTE_URL", "https://compute.example.test")
    monkeypatch.setenv("NEXORA_MANAGED_COMPUTE_SECRET", "server-only-secret")
    monkeypatch.delenv("NEXORA_MANAGED_COMPUTE_ALLOW_HTTP", raising=False)

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return json.dumps({
                "decision": "managed_server_candidate",
                "execution_location": "managed_server",
                "job_submission_enabled": False,
            }).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = {key.lower(): value for key, value in request.header_items()}
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(api_main, "urlopen", fake_urlopen)
    payload = api_main.ManagedComputePlanRequest(
        workload="procedural_3d",
        consent_to_share_hardware_metrics=True,
        local_profile={
            "machine": {
                "logical_cpu_count": 4,
                "cpu_available_cores": 2.5,
                "ram_total_gib": 7.9,
                "ram_available_gib": 2.33,
                "disk_free_gib": 356,
                "disk_root": "C:\\Private",
            },
            "tools": {"blender": {"available": False, "path": "C:\\private\\blender.exe"}},
        },
    )

    result = api_main.managed_compute_plan(payload)

    assert result["execution_location"] == "managed_server"
    assert captured["url"] == "https://compute.example.test/internal/plan"
    assert captured["headers"]["x-nexora-compute-key"] == "server-only-secret"
    assert captured["body"]["local_profile"]["machine"]["ram_available_gib"] == 2.33
    assert "disk_root" not in captured["body"]["local_profile"]["machine"]
    assert "path" not in captured["body"]["local_profile"]["tools"]["blender"]
    assert captured["timeout"] == 18


def test_managed_compute_private_http_requires_explicit_enablement(monkeypatch):
    monkeypatch.setenv("NEXORA_MANAGED_COMPUTE_URL", "http://nexora-managed-compute:10000")
    monkeypatch.setenv("NEXORA_MANAGED_COMPUTE_SECRET", "server-only-secret")
    monkeypatch.delenv("NEXORA_MANAGED_COMPUTE_ALLOW_HTTP", raising=False)

    with pytest.raises(HTTPException) as error:
        api_main._managed_compute_request("/internal/capabilities")

    assert error.value.status_code == 503
    assert "HTTPS" in error.value.detail
