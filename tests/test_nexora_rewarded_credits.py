import base64
import time

import pytest
from fastapi import HTTPException, Request
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from core.nexora_workspace import creator_workflow


def _request_with_query(query: bytes) -> Request:
    path = b"/api/v1/creator-flow/rewards/admob/ssv"
    return Request({
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": path.decode("ascii"),
        "raw_path": path,
        "query_string": query,
        "headers": [],
        "client": ("testclient", 12345),
        "server": ("nexora.test", 443),
    })


def _signed_callback(private_key, *, transaction_id="txn-verified-001") -> bytes:
    timestamp = str(int(time.time() * 1000))
    signed = (
        "ad_network=5450213213286189855"
        "&ad_unit=123456789012"
        "&custom_data=reward-intent-token-abcdefghijklmnopqrstuvwxyz"
        "&reward_amount=1"
        "&reward_item=nexora_basic_tool_credit"
        f"&timestamp={timestamp}"
        f"&transaction_id={transaction_id}"
        "&user_id=nexora-user-001"
    ).encode("ascii")
    signature = private_key.sign(signed, ec.ECDSA(hashes.SHA256()))
    encoded = base64.urlsafe_b64encode(signature).rstrip(b"=")
    return signed + b"&signature=" + encoded + b"&key_id=987654321"


def test_pochi_number_normalizes_owner_supplied_international_number(monkeypatch):
    monkeypatch.setenv("NEXORA_POCHI_MERCHANT_NUMBER", "+254742466828")
    assert creator_workflow._pochi_merchant_number() == "0742466828"


def test_pochi_default_is_owner_supplied_number(monkeypatch):
    monkeypatch.delenv("NEXORA_POCHI_MERCHANT_NUMBER", raising=False)
    assert creator_workflow._pochi_merchant_number() == "0742466828"


def test_admob_ssv_verifies_google_signed_query_and_returns_reward(monkeypatch):
    private_key = ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setattr(
        creator_workflow,
        "_load_admob_public_keys",
        lambda: {987654321: private_key.public_key()},
    )
    monkeypatch.setenv(
        "NEXORA_ADMOB_REWARDED_AD_UNIT_ID",
        "ca-app-pub-1234567890123456/123456789012",
    )
    monkeypatch.setenv("NEXORA_REWARDED_ADMOB_REWARD_ITEM", "nexora_basic_tool_credit")
    monkeypatch.setenv("NEXORA_REWARDED_ADMOB_REWARD_AMOUNT", "1")

    callback = creator_workflow._verify_admob_ssv_signature(
        _request_with_query(_signed_callback(private_key))
    )

    assert callback["intent_id"] == "reward-intent-token-abcdefghijklmnopqrstuvwxyz"
    assert callback["user_id"] == "nexora-user-001"
    assert callback["ad_unit_id"] == "123456789012"
    assert callback["reward_amount"] == "1"
    assert callback["transaction_id"] == "txn-verified-001"


def test_admob_ssv_rejects_tampered_query(monkeypatch):
    private_key = ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setattr(
        creator_workflow,
        "_load_admob_public_keys",
        lambda: {987654321: private_key.public_key()},
    )
    monkeypatch.setenv(
        "NEXORA_ADMOB_REWARDED_AD_UNIT_ID",
        "ca-app-pub-1234567890123456/123456789012",
    )
    query = _signed_callback(private_key).replace(b"reward_amount=1", b"reward_amount=2")

    with pytest.raises(HTTPException) as error:
        creator_workflow._verify_admob_ssv_signature(_request_with_query(query))

    assert error.value.status_code == 403


def test_admob_ssv_rejects_an_unconfigured_ad_unit(monkeypatch):
    private_key = ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setattr(
        creator_workflow,
        "_load_admob_public_keys",
        lambda: {987654321: private_key.public_key()},
    )
    monkeypatch.delenv("NEXORA_ADMOB_REWARDED_AD_UNIT_ID", raising=False)

    with pytest.raises(HTTPException) as error:
        creator_workflow._verify_admob_ssv_signature(
            _request_with_query(_signed_callback(private_key))
        )

    assert error.value.status_code == 503
