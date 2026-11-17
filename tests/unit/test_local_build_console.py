from pathlib import Path
import struct

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from services.api.local_build import (
    AndroidBuildRequest,
    _android_export_command,
    _require_desktop,
    _write_android_preset,
)
from services.api.android_toolchain import sdk_components, set_editor_resource_value


def request(**overrides):
    values = {
        "app_name": "NEXORA Sample",
        "package_id": "co.nexora.samplegame",
        "version_name": "1.2.3",
        "version_code": 12,
        "build_type": "release",
        "output_format": "aab",
    }
    values.update(overrides)
    return AndroidBuildRequest.model_validate(values)


def png_header(width: int = 512, height: int = 512) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 4 + b"IHDR" + struct.pack(">II", width, height)


def project_with_presets(tmp_path: Path) -> Path:
    project = tmp_path / "game"
    project.mkdir()
    (project / "export_presets.cfg").write_text(
        '[preset.0]\nname="Linux/X11"\n\n[preset.1]\nname="Windows Desktop"\n\n',
        encoding="utf-8",
    )
    (project / "project.godot").write_text(
        '[application]\nconfig/name="NEXORA"\n\n'
        '[display]\nwindow/size/viewport_width=1280\nwindow/size/viewport_height=720\n\n'
        '[rendering]\nrenderer/rendering_method="gl_compatibility"\n',
        encoding="utf-8",
    )
    return project


def test_android_build_request_accepts_signed_release_aab():
    result = request()
    assert result.output_format == "aab"
    assert result.build_type == "release"
    assert result.package_id == "co.nexora.samplegame"


def test_android_build_request_rejects_debug_aab():
    with pytest.raises(ValidationError):
        request(build_type="debug", output_format="aab")


@pytest.mark.parametrize(
    "package_id",
    ["bad", "Com.Example.game", "com..game", "com.example.2game", "com example.game"],
)
def test_android_build_request_rejects_invalid_package_ids(package_id):
    with pytest.raises(ValidationError):
        request(package_id=package_id)


def test_android_build_request_rejects_target_sdk_below_minimum():
    with pytest.raises(ValidationError):
        request(min_sdk=28, target_sdk=27)


def test_godot_internet_permission_cannot_be_disabled():
    with pytest.raises(ValidationError):
        request(permissions={"internet": False})


def test_android_preset_keeps_existing_platform_presets_and_does_not_store_secrets(tmp_path: Path):
    project = project_with_presets(tmp_path)
    output = project / "builds" / "android" / "sample.aab"
    output.parent.mkdir(parents=True)

    _write_android_preset(project, request(), output)

    preset = (project / "export_presets.cfg").read_text(encoding="utf-8")
    assert "[preset.0]" in preset
    assert "[preset.1]" in preset
    assert "[preset.2]" in preset
    assert 'package/unique_name="co.nexora.samplegame"' in preset
    assert 'package/name="NEXORA Sample"' in preset
    assert "gradle_build/use_gradle_build=true" in preset
    assert "gradle_build/export_format=1" in preset
    assert "version/code=12" in preset
    assert 'keystore/release_password=""' in preset
    assert "key_password" not in preset


def test_android_preset_sets_portrait_orientation_in_project_settings(tmp_path: Path):
    project = project_with_presets(tmp_path)
    output = project / "builds" / "android" / "portrait.apk"
    output.parent.mkdir(parents=True)

    _write_android_preset(project, request(output_format="apk", orientation="portrait"), output)

    settings = (project / "project.godot").read_text(encoding="utf-8")
    preset = (project / "export_presets.cfg").read_text(encoding="utf-8")
    assert "window/handheld/orientation=1" in settings
    assert "window/size/viewport_width=720" in settings
    assert "window/size/viewport_height=1280" in settings
    assert 'renderer/rendering_method="gl_compatibility"' in settings
    assert "screen/orientation=" not in preset


def test_android_preset_accepts_project_icon_and_uses_adaptive_icon_slot(tmp_path: Path):
    project = project_with_presets(tmp_path)
    source = project / "incoming" / "creator-icon.png"
    source.parent.mkdir()
    source.write_bytes(png_header())
    output = project / "builds" / "android" / "sample.apk"
    output.parent.mkdir(parents=True)

    _write_android_preset(project, request(output_format="apk", icon_path=str(source)), output)

    preset = (project / "export_presets.cfg").read_text(encoding="utf-8")
    assert 'launcher_icons/main_192x192="res://android_assets/launcher-icon.png"' in preset
    assert 'launcher_icons/adaptive_foreground_432x432="res://android_assets/launcher-icon.png"' in preset
    assert (project / "android_assets" / "launcher-icon.png").is_file()


def test_android_preset_reuses_uploaded_project_icon_without_copying_onto_itself(tmp_path: Path):
    project = project_with_presets(tmp_path)
    source = project / "android_assets" / "launcher-icon.png"
    source.parent.mkdir()
    source.write_bytes(png_header())
    output = project / "builds" / "android" / "sample.apk"
    output.parent.mkdir(parents=True)

    _write_android_preset(project, request(output_format="apk", icon_path=str(source)), output)

    assert source.is_file()


def test_android_preset_rejects_icon_outside_current_project(tmp_path: Path):
    project = project_with_presets(tmp_path)
    external = tmp_path / "external.png"
    external.write_bytes(png_header())
    output = project / "builds" / "android" / "sample.apk"
    output.parent.mkdir(parents=True)

    with pytest.raises(HTTPException):
        _write_android_preset(project, request(output_format="apk", icon_path=str(external)), output)


def test_android_export_command_installs_gradle_template_with_aab_export(tmp_path: Path):
    project = tmp_path / "game"
    output = project / "builds" / "android" / "game.aab"

    command = _android_export_command("godot", project, "--export-release", output, True)

    assert "--install-android-build-template" in command
    assert command.index("--install-android-build-template") < command.index("--export-release")
    assert command[-3:] == ["--export-release", "Android", str(output)]


def test_android_export_command_does_not_install_gradle_template_for_apk(tmp_path: Path):
    project = tmp_path / "game"
    output = project / "builds" / "android" / "game.apk"

    command = _android_export_command("godot", project, "--export-debug", output, False)

    assert "--install-android-build-template" not in command
    assert command[-3:] == ["--export-debug", "Android", str(output)]


def test_sdk_component_check_fails_closed_for_missing_components(tmp_path: Path):
    report = sdk_components(tmp_path / "empty-sdk")

    assert report["available"] is False
    assert "platform-tools / adb" in report["missing"]
    assert "ndk;28.1.13356709" in report["missing"]


def test_editor_setting_update_preserves_existing_preferences():
    original = (
        '[gd_resource type="EditorSettings" format=3]\n\n[resource]\n'
        'interface/editor/display_scale=1\n'
    )
    updated = set_editor_resource_value(original, "export/android/android_sdk_path", "/opt/android-sdk")
    updated = set_editor_resource_value(updated, "export/android/java_sdk_path", "/opt/jdk-17")

    assert "interface/editor/display_scale=1" in updated
    assert 'export/android/android_sdk_path = "/opt/android-sdk"' in updated
    assert 'export/android/java_sdk_path = "/opt/jdk-17"' in updated


def test_editor_setting_update_replaces_existing_value_without_duplicate():
    original = (
        '[gd_resource type="EditorSettings" format=3]\n\n[resource]\n'
        'export/android/android_sdk_path = "/old/sdk"\n'
    )
    updated = set_editor_resource_value(original, "export/android/android_sdk_path", "/new/sdk")

    assert updated.count("export/android/android_sdk_path") == 1
    assert 'export/android/android_sdk_path = "/new/sdk"' in updated


def test_desktop_build_controls_require_explicit_opt_in(monkeypatch):
    monkeypatch.delenv("PGF_ENABLE_DESKTOP_BUILD_CONSOLE", raising=False)
    monkeypatch.setenv("PGF_REQUIRE_CLOUD_DEPENDENCIES", "false")
    with pytest.raises(HTTPException):
        _require_desktop()


def test_desktop_build_controls_remain_disabled_in_hosted_mode(monkeypatch):
    monkeypatch.setenv("PGF_ENABLE_DESKTOP_BUILD_CONSOLE", "true")
    monkeypatch.setenv("PGF_REQUIRE_CLOUD_DEPENDENCIES", "true")
    with pytest.raises(HTTPException):
        _require_desktop()


def test_desktop_build_controls_can_be_enabled_on_local_api(monkeypatch):
    monkeypatch.setenv("PGF_ENABLE_DESKTOP_BUILD_CONSOLE", "true")
    monkeypatch.setenv("PGF_REQUIRE_CLOUD_DEPENDENCIES", "false")
    _require_desktop()
