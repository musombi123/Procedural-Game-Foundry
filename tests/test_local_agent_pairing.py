from __future__ import annotations

from fastapi.testclient import TestClient

from services.worker import local_agent
from services.worker.local_security import PairingAuthority


def test_local_agent_pairing_requires_explicit_user_consent(monkeypatch):
    authority = PairingAuthority()
    monkeypatch.setattr(local_agent, "get_pairing_authority", lambda: authority)

    def account_verification_must_not_run(_token: str):
        raise AssertionError("Account verification must wait for explicit user consent.")

    monkeypatch.setattr(local_agent, "_verify_cloud_account", account_verification_must_not_run)
    client = TestClient(local_agent.app, base_url="http://127.0.0.1:8765")

    response = client.post(
        "/pair",
        json={"account_access_token": "x" * 40, "consent": False},
        headers={"Origin": "https://revelacode.co.ke"},
    )

    assert response.status_code == 403
    assert "Approve" in response.json()["detail"]


def test_local_agent_pairing_issues_session_only_for_verified_account(monkeypatch):
    authority = PairingAuthority()
    cloud_token = "verified-cloud-session-" + ("x" * 32)
    monkeypatch.setattr(local_agent, "get_pairing_authority", lambda: authority)
    monkeypatch.setattr(
        local_agent,
        "_verify_cloud_account",
        lambda supplied: {"id": "creator-123"} if supplied == cloud_token else {},
    )
    client = TestClient(local_agent.app, base_url="http://127.0.0.1:8765")

    response = client.post(
        "/pair",
        json={"account_access_token": cloud_token, "consent": True},
        headers={"Origin": "https://revelacode.co.ke"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["pairing_method"] == "explicit_user_approval"
    assert payload["expires_in_seconds"] == 12 * 60 * 60
    assert payload["access_token"] != cloud_token
    principal = authority.resolve(payload["access_token"])
    assert principal is not None
    assert principal.user_id == "creator-123"
    assert principal.cloud_access_token == cloud_token
    assert cloud_token not in response.text


def test_local_pairing_authority_tokens_can_be_revoked():
    authority = PairingAuthority()
    token, expires_at = authority.issue("creator-123", "verified-cloud-session-" + ("x" * 32))

    assert expires_at > 0
    assert authority.resolve(token).user_id == "creator-123"
    assert authority.revoke(token) is True
    assert authority.resolve(token) is None
