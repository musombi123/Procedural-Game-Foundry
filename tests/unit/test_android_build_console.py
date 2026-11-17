import pytest
from pydantic import ValidationError

from services.api.workspace import AndroidBuildSettings
from services.worker.runner import _write_export_presets


def test_android_build_settings_accept_valid_mobile_release_configuration():
    settings = AndroidBuildSettings(
        app_name="NEXORA Racer",
        package_id="ke.revelacode.nexora.racer",
        version_name="1.2.0",
        version_code=12,
        build_type="release",
        artifact_format="aab",
        orientation="portrait",
        camera_permission=True,
        microphone_permission=True,
    )
    assert settings.package_id == "ke.revelacode.nexora.racer"
    assert settings.artifact_format == "aab"
    assert settings.build_type == "release"


@pytest.mark.parametrize("package_id", ["com", "bad.package.", "com..game", "com/game"])
def test_android_build_settings_reject_invalid_package_ids(package_id):
    with pytest.raises(ValidationError):
        AndroidBuildSettings(package_id=package_id)


def test_android_export_preset_uses_creator_settings(tmp_path):
    _write_export_presets(tmp_path, {
        "app_name": "NEXORA Racer",
        "package_id": "ke.revelacode.racer",
        "version_name": "2.3.1",
        "version_code": 23,
        "orientation": "portrait",
        "internet_permission": True,
        "camera_permission": True,
        "microphone_permission": False,
    })
    preset = (tmp_path / "export_presets.cfg").read_text(encoding="utf-8")
    assert 'package/unique_name="ke.revelacode.racer"' in preset
    assert 'package/name="NEXORA Racer"' in preset
    assert 'version/name="2.3.1"' in preset
    assert "version/code=23" in preset
    assert "screen/orientation=1" in preset
    assert "permissions/camera=true" in preset
    assert "permissions/record_audio=false" in preset
