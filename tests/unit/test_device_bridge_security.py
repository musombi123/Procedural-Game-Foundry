import pytest
from nexora_device_bridge.security import PairingState, validate_package_id, validate_private_pair_address, validate_serial

def test_pairing_code_is_single_use_and_token_is_required():
    state = PairingState(code="12345678", token="long-secret-token")
    token = state.pair("12345678")
    assert token == "long-secret-token"
    assert state.paired is True
    assert state.pair("12345678") is None
    assert state.authorize(token) is True
    assert state.authorize("wrong") is False

def test_pairing_locks_after_five_failed_attempts():
    state = PairingState(code="12345678", token="long-secret-token")
    for _ in range(5):
        assert state.pair("00000000") is None
    assert state.pair("12345678") is None

@pytest.mark.parametrize("package_id", ["com", "bad.package.", "com..game", "com/game", ""])
def test_invalid_package_ids_are_rejected(package_id):
    with pytest.raises(ValueError):
        validate_package_id(package_id)

def test_valid_package_id_and_serial():
    assert validate_package_id("ke.revelacode.nexora.game") == "ke.revelacode.nexora.game"
    assert validate_serial("R58M123ABC") == "R58M123ABC"

def test_wireless_pairing_rejects_public_ip():
    with pytest.raises(ValueError):
        validate_private_pair_address("8.8.8.8", 37123)

def test_wireless_pairing_accepts_private_lan_ip():
    assert validate_private_pair_address("192.168.1.20", 37123) == ("192.168.1.20", 37123)
