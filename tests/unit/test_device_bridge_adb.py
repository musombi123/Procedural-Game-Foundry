import hashlib
from pathlib import Path
import pytest
from nexora_device_bridge import adb

def test_list_devices_parses_authorized_and_unauthorized_states(monkeypatch):
    monkeypatch.setattr(adb, "run_adb", lambda args, timeout=30: "List of devices attached\nABC123 device product:foo model:Pixel_7\nXYZ unauthorized usb:1-1\n")
    devices = adb.list_devices()
    assert devices == [
        {"serial": "ABC123", "state": "device", "model": "Pixel_7", "product": "foo"},
        {"serial": "XYZ", "state": "unauthorized", "model": "", "product": ""},
    ]

def test_install_checks_package_id_signature_and_checksum(tmp_path, monkeypatch):
    apk = tmp_path / "build.apk"
    apk.write_bytes(b"test-apk-content")
    monkeypatch.setattr(adb, "verify_apk_signature", lambda path: None)
    monkeypatch.setattr(adb, "inspect_apk", lambda path: {"package_id": "ke.revelacode.game"})
    monkeypatch.setattr(adb, "run_adb", lambda args, timeout=30: "Success")
    result = adb.install_apk_file("ABC123", "ke.revelacode.game", apk)
    assert result["sha256"] == hashlib.sha256(b"test-apk-content").hexdigest()
    assert result["install_output"] == "Success"

def test_install_rejects_package_mismatch(tmp_path, monkeypatch):
    apk = tmp_path / "build.apk"
    apk.write_bytes(b"test-apk-content")
    monkeypatch.setattr(adb, "verify_apk_signature", lambda path: None)
    monkeypatch.setattr(adb, "inspect_apk", lambda path: {"package_id": "ke.other.game"})
    with pytest.raises(adb.AdbError, match="package ID mismatch"):
        adb.install_apk_file("ABC123", "ke.revelacode.game", apk)
