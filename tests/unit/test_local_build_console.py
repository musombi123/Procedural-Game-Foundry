from pathlib import Path

import pytest
from pydantic import ValidationError

from services.api.local_build import (
    AndroidBuildRequest,
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


def test_android_preset_keeps_export_settings_without_secrets(tmp_path: Path):
    project = tmp_path / "game"
    project.mkdir()
    (project / "export_presets.cfg").write_text(
        '[preset.0]\nname="Linux/X11"\n\n[preset.1]\nname="Windows Desktop"\n\n[preset.2]\nname="Android"\n',
        encoding="utf-8",
    )
    output = project / "builds" / "android" / "sample.aab"
    output.parent.mkdir(parents=True)
    request = _request()
    _write_android_preset(project, request, output)

    result = (project / "export_presets.cfg").read_text(encoding="utf-8")
    assert '[preset.0]' in result
    assert '[preset.1]' in result
    assert 'name="Android"' in result
    assert 'gradle_build/use_gradle_build=true' in result
    assert 'gradle_build/export_format=1' in result
    assert 'package/unique_name="co.nexora.samplegame"' in result
    assert 'package/name="NEXORA Sample"' in result
    assert 'version/code=12' in result
    assert 'keystore/release_password=""' in result
    assert "key_password" not in result
