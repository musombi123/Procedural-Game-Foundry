from services.api import auth


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload

    def json(self):
        return self.payload


def test_identity_is_derived_from_backend_verified_me_endpoint(monkeypatch):
    monkeypatch.setenv("PGF_IDENTITY_INTROSPECTION_URL", "https://revelacode-backend.onrender.com/api/auth/me")
    captured = {}

    def fake_get(url, headers, timeout, follow_redirects):
        captured["url"] = url
        captured["authorization"] = headers["Authorization"]
        return FakeResponse(200, {"success": True, "user": {"id": "account-123", "full_name": "Creator"}})

    monkeypatch.setattr(auth.httpx, "get", fake_get)
    profile = auth.verify_identity_token("Bearer valid-session")
    assert profile == {"id": "account-123", "name": "Creator"}
    assert captured["authorization"] == "Bearer valid-session"


def test_identity_rejects_missing_and_revoked_credentials(monkeypatch):
    from fastapi import HTTPException
    import pytest

    with pytest.raises(HTTPException) as missing:
        auth.verify_identity_token(None)
    assert missing.value.status_code == 401

    monkeypatch.setenv("PGF_IDENTITY_INTROSPECTION_URL", "https://revelacode-backend.onrender.com/api/auth/me")
    monkeypatch.setattr(auth.httpx, "get", lambda *args, **kwargs: FakeResponse(401, {"code": "session_revoked"}))
    with pytest.raises(HTTPException) as revoked:
        auth.verify_identity_token("Bearer revoked-session")
    assert revoked.value.status_code == 401



def test_identity_rejects_malformed_backend_json(monkeypatch):
    from fastapi import HTTPException
    import pytest

    monkeypatch.setenv("PGF_IDENTITY_INTROSPECTION_URL", "https://revelacode-backend.onrender.com/api/auth/me")

    def invalid_json(*args, **kwargs):
        raise ValueError("invalid json")

    monkeypatch.setattr(auth.httpx, "get", lambda *args, **kwargs: FakeResponse(200, None))
    class InvalidJsonResponse(FakeResponse):
        def json(self):
            return invalid_json()

    monkeypatch.setattr(auth.httpx, "get", lambda *args, **kwargs: InvalidJsonResponse(200, None))
    with pytest.raises(HTTPException) as result:
        auth.verify_identity_token("Bearer valid-session")
    assert result.value.status_code == 503
