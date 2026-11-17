from pathlib import Path
import struct

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from services.api.local_build import (
    AndroidBuildRequest,
    _android_export_command,
    _android_sdk_components,
    _set_editor_resource_value,
    _write_android_preset,
)


def _request(**overrides):
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


def test_android_build_request_accepts_release_aab():
    request = _request()
    assert request.output_format == "aab"
    assert request.build_type == "release"
    assert request.package_id == "co.nexora.samplegame"


def test_android_build_request_rejects_debug_aab():
    with pytest.raises(ValidationError):
        _request(build_type="debug", output_format="aab")


@pytest.mark.parametrize("package_id", ["bad", "Com.Example.game", "com..game", "com.example.2game", "com example.game"])
def test_android_build_request_rejects_invalid_package_ids(package_id):
    with pytest.raises(ValidationError):
        _request(package_id=package_id)


def test_android_build_request_rejects_target_sdk_below_minimum():
    with pytest.raises(ValidationError):
        _request(min_sdk=28, target_sdk=27)


def _write_project_preset(project: Path) -> None:
    (project / "export_presets.cfg").write_text(
        '[preset.0]\nname="Linux/X11"\n\n[preset.1]\nname="Windows Desktop"\n\n[preset.2]\nname="Android"\n',
        encoding="utf-8",
    )


def test_android_preset_keeps_export_settings_without_secrets(tmp_path: Path):
    project = tmp_path / "game"
    project.mkdir()
    _write_project_preset(project)
    output = project / "builds" / "android" / "sample.aab"
    output.parent.mkdir(parents=True)
    _write_android_preset(project, _request(), output)

    result = (project / "export_presets.cfg").read_text(encoding="utf-8")
    assert "[preset.0]" in result
    assert "[preset.1]" in result
    assert 'name="Android"' in result
    assert "gradle_build/use_gradle_build=true" in result
    assert "gradle_build/export_format=1" in result
    assert 'package/unique_name="co.nexora.samplegame"' in result
    assert 'package/name="NEXORA Sample"' in result
    assert "version/code=12" in result
    assert 'keystore/release_password=""' in result
    assert "key_password" not in result


def test_android_preset_accepts_project_icon_and_uses_adaptive_slot(tmp_path: Path):
    project = tmp_path / "game"
    project.mkdir()
    _write_project_preset(project)
    source = project / "incoming" / "creator-icon.png"
    source.parent.mkdir()
    png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 4 + b"IHDR" + struct.pack(">II", 512, 512)
    source.write_bytes(png_header)
    output = project / "builds" / "android" / "sample.apk"
    output.parent.mkdir(parents=True)

    _write_android_preset(project, _request(output_format="apk", icon_path=str(source)), output)

    result = (project / "export_presets.cfg").read_text(encoding="utf-8")
    assert 'launcher_icons/main_192x192="res://android_assets/launcher-icon.png"' in result
    assert 'launcher_icons/adaptive_foreground_432x432="res://android_assets/launcher-icon.png"' in result
    assert (project / "android_assets" / "launcher-icon.png").is_file()


def test_android_preset_rejects_icon_outside_project(tmp_path: Path):
    project = tmp_path / "game"
    project.mkdir()
    _write_project_preset(project)
    external = tmp_path / "external.png"
    external.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 4 + b"IHDR" + struct.pack(">II", 512, 512))
    output = project / "builds" / "android" / "sample.apk"
    output.parent.mkdir(parents=True)

    with pytest.raises(HTTPException):
        _write_android_preset(project, _request(output_format="apk", icon_path=str(external)), output)


def test_editor_setting_update_preserves_existing_preferences():
    original = '[gd_resource type="EditorSettings" format=3]\n\n[resource]\ninterface/editor/display_scale=1\n'
    updated = _set_editor_resource_value(original, "export/android/android_sdk_path", "/opt/android-sdk")
    updated = _set_editor_resource_value(updated, "export/android/java_sdk_path", "/opt/jdk-17")

    assert "interface/editor/display_scale=1" in updated
    assert 'export/android/android_sdk_path = "/opt/android-sdk"' in updated
    assert 'export/android/java_sdk_path = "/opt/jdk-17"' in updated


def test_editor_setting_update_replaces_existing_value_without_duplicate():
    original = '[gd_resource type="EditorSettings" format=3]\n\n[resource]\nexport/android/android_sdk_path = "/old/sdk"\n'
    updated = _set_editor_resource_value(original, "export/android/android_sdk_path", "/new/sdk")

    assert updated.count("export/android/android_sdk_path") == 1
    assert 'export/android/android_sdk_path = "/new/sdk"' in updated


def test_android_sdk_component_check_fails_closed_for_missing_components(tmp_path: Path):
    result = _android_sdk_components(tmp_path / "empty-sdk")

    assert result["available"] is False
    assert "platform-tools / adb" in result["missing"]
    assert "ndk;28.1.13356709" in result["missing"]



def test_aab_gradle_template_flag_is_combined_with_release_export(tmp_path: Path):
    project = tmp_path / "game"
    output = project / "builds" / "android" / "game.aab"

    command = _android_export_command("godot", project, "--export-release", output, True)

    assert "--install-android-build-template" in command
    assert command.index("--install-android-build-template") < command.index("--export-release")
    assert command[-3:] == ["--export-release", "Android", str(output)]


def test_debug_apk_export_does_not_install_gradle_template(tmp_path: Path):
    project = tmp_path / "game"
    output = project / "builds" / "android" / "game.apk"

    command = _android_export_command("godot", project, "--export-debug", output, False)

    assert "--install-android-build-template" not in command
    assert command[-3:] == ["--export-debug", "Android", str(output)]



def test_android_preset_writes_orientation_to_project_settings(tmp_path: Path):
    project = tmp_path / "game"
    project.mkdir()
    _write_project_preset(project)
    project_file = project / "project.godot"
    project_file.write_text(
        '[application]\nconfig/name="NEXORA"\n\n[display]\nwindow/size/viewport_width=1280\nwindow/size/viewport_height=720\n\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n',
        encoding="utf-8",
    )
    output = project / "builds" / "android" / "portrait.apk"
    output.parent.mkdir(parents=True)

    _write_android_preset(project, _request(output_format="apk", orientation="portrait"), output)

    settings = project_file.read_text(encoding="utf-8")
    preset = (project / "export_presets.cfg").read_text(encoding="utf-8")
    assert "window/handheld/orientation=1" in settings
    assert "window/size/viewport_width=720" in settings
    assert "window/size/viewport_height=1280" in settings
    assert 'renderer/rendering_method="gl_compatibility"' in settings
    assert "screen/orientation=" not in preset


def test_uploaded_launcher_icon_can_be_used_without_copying_file_onto_itself(tmp_path: Path):
    project = tmp_path / "game"
    project.mkdir()
    _write_project_preset(project)
    source = project / "android_assets" / "launcher-icon.png"
    source.parent.mkdir()
    source.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 4 + b"IHDR" + struct.pack(">II", 512, 512))
    output = project / "builds" / "android" / "sample.apk"
    output.parent.mkdir(parents=True)

    _write_android_preset(project, _request(output_format="apk", icon_path=str(source)), output)

    assert source.is_file()
    assert 'launcher_icons/adaptive_foreground_432x432="res://android_assets/launcher-icon.png"' in (project / "export_presets.cfg").read_text(encoding="utf-8")


def test_android_internet_permission_is_mandatory_for_godot_export():
    with pytest.raises(ValidationError):
        _request(permissions={"internet": False})
