from services.worker.workload_planner import plan_execution


def _profile(cpu, total, available, disk, tools=None, gpu=None, android=None):
    return {
        "machine": {
            "logical_cpu_count": cpu,
            "cpu_available_cores": cpu,
            "ram_total_gib": total,
            "ram_available_gib": available,
            "disk_free_gib": disk,
        },
        "tools": {
            key: {"available": True}
            for key in (tools or ())
        } | {"python": {"available": True}},
        "gpu": gpu or {"accelerators": [], "nvidia_cuda_available": False, "primary": None},
        "android": android or {},
    }


def _server():
    return {
        **_profile(
            4, 16, 12, 120,
            tools=("blender", "godot", "ffmpeg", "ffprobe", "java", "adb"),
            android={"sdk_root": "/opt/android-sdk", "build_tools_installed": True, "ready_to_verify_apk": True},
        ),
        "available": True,
    }


def test_lightweight_workspace_work_stays_on_creator_pc_with_modest_resources():
    local = _profile(4, 7.9, 2.33, 356)
    result = plan_execution("workspace_editing", local, _server())
    assert result["decision"] == "run_locally"
    assert result["execution_location"] == "creator_device"
    assert result["requires_remote_project_transfer"] is False


def test_procedural_3d_falls_back_to_managed_server_when_local_tools_and_headroom_are_missing():
    local = _profile(4, 7.9, 2.33, 356)
    result = plan_execution("procedural_3d", local, _server())
    assert result["decision"] == "managed_server_candidate"
    assert result["execution_location"] == "managed_server"
    assert result["requires_remote_project_transfer"] is True
    assert result["requires_remote_upload_confirmation"] is True
    assert result["job_submission_enabled"] is False


def test_movie_processing_falls_back_when_local_ram_headroom_and_ffmpeg_are_missing():
    local = _profile(4, 7.9, 2.33, 356)
    result = plan_execution("movie_processing", local, _server())
    assert result["execution_location"] == "managed_server"


def test_android_export_uses_server_sdk_without_requiring_local_adb():
    local = _profile(4, 7.9, 2.33, 356)
    result = plan_execution("android_export", local, _server())
    assert result["execution_location"] == "managed_server"


def test_procedural_3d_stays_on_user_pc_when_live_cpu_ram_storage_and_tools_are_sufficient():
    local = _profile(
        8, 32, 20, 100,
        tools=("blender", "godot", "ffmpeg", "ffprobe"),
    )

    result = plan_execution("procedural_3d", local, _server())

    assert result["decision"] == "run_locally"
    assert result["execution_location"] == "creator_device"
    assert result["requires_remote_project_transfer"] is False


def test_busy_user_cpu_causes_managed_candidate_when_server_is_ready():
    local = _profile(
        8, 32, 20, 100,
        tools=("blender", "godot"),
    )
    local["machine"]["cpu_available_cores"] = 0.5

    result = plan_execution("procedural_3d", local, _server())

    assert result["execution_location"] == "managed_server"
    assert any("CPU is currently busy" in item for item in result["local"]["failures"])


def test_low_available_user_ram_causes_managed_candidate_even_with_large_installed_ram():
    local = _profile(
        8, 32, 100, 100,
        tools=("blender", "godot"),
    )
    local["machine"]["ram_available_gib"] = 1.5

    result = plan_execution("procedural_3d", local, _server())

    assert result["execution_location"] == "managed_server"
    assert any("Available RAM" in item for item in result["local"]["failures"])


def test_core_server_without_optional_android_sdk_still_accepts_3d_and_movie_candidates():
    local = _profile(4, 7.9, 2.33, 356)
    core_only_server = {
        **_profile(
            4, 16, 12, 120,
            tools=("blender", "godot", "ffmpeg", "ffprobe", "java"),
        ),
        "available": True,
        "execution_ready": True,
    }

    procedural = plan_execution("procedural_3d", local, core_only_server)
    movie = plan_execution("movie_processing", local, core_only_server)
    android = plan_execution("android_export", local, core_only_server)

    assert procedural["execution_location"] == "managed_server"
    assert movie["execution_location"] == "managed_server"
    assert android["execution_location"] == "unavailable"
    assert android["job_submission_enabled"] is False


def test_server_without_persistent_workspace_is_not_selected_even_when_tools_exist():
    local = _profile(4, 7.9, 2.33, 356)
    server = {**_server(), "execution_ready": False}

    result = plan_execution("movie_processing", local, server)

    assert result["execution_location"] == "unavailable"
    assert result["decision"] == "wait_for_capacity"
    assert result["requires_remote_project_transfer"] is False
    assert result["job_submission_enabled"] is False


def test_heavy_render_is_not_routed_to_an_undersized_standard_worker():
    local = _profile(4, 7.9, 2.33, 356)
    result = plan_execution("heavy_3d_render", local, _server())
    assert result["decision"] == "wait_for_capacity"
    assert result["execution_location"] == "unavailable"


def test_image_to_3d_is_not_claimed_available_without_cuda():
    local = _profile(4, 7.9, 2.33, 356)
    result = plan_execution("image_to_3d", local, _server())
    assert result["execution_location"] == "unavailable"


def test_unknown_workload_is_rejected():
    import pytest
    with pytest.raises(ValueError, match="Unknown NEXORA workload profile"):
        plan_execution("arbitrary_shell", {}, _server())


def test_remote_candidate_requires_verified_persistent_execution_storage():
    local = _profile(4, 7.9, 2.33, 356)
    managed = {**_server(), "execution_ready": False}

    result = plan_execution("procedural_3d", local, managed)

    assert result["decision"] == "wait_for_capacity"
    assert result["execution_location"] == "unavailable"
    assert result["managed_server"]["ready"] is False
    assert result["job_submission_enabled"] is False
