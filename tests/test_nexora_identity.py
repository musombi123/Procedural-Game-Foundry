from fastapi import FastAPI
from pydantic import ValidationError
import pytest

from core.nexora_workspace.identity import (
    LoginPayload,
    NexoraIdentityUnavailable,
    RegistrationPayload,
    TourProgressPayload,
    _connect,
    _database_url,
    hash_password,
    register_nexora_auth_routes,
    verify_password,
)


def test_password_hash_is_salted_and_verifiable():
    password = "Nexora-Test-Password-2026!"
    first = hash_password(password)
    second = hash_password(password)

    assert first != second
    assert password not in first
    assert verify_password(password, first)
    assert not verify_password("incorrect-password", first)


def test_registration_normalizes_email_and_display_name():
    payload = RegistrationPayload.model_validate({
        "email": "  DEV@Example.COM ",
        "display_name": "  Game   Creator  ",
        "password": "Nexora-Test-Password-2026!",
    })

    assert payload.email == "dev@example.com"
    assert payload.display_name == "Game Creator"


def test_registration_rejects_short_password():
    with pytest.raises(ValidationError):
        RegistrationPayload.model_validate({
            "email": "dev@example.com",
            "display_name": "Game Creator",
            "password": "short",
        })


def test_login_normalizes_email():
    payload = LoginPayload.model_validate({
        "email": "  DEV@Example.COM ",
        "password": "some-password",
    })
    assert payload.email == "dev@example.com"


def test_nexora_database_does_not_fall_back_to_generic_database_url(monkeypatch):
    monkeypatch.delenv("NEXORA_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://revelacode/shared")

    assert _database_url() == ""
    with pytest.raises(NexoraIdentityUnavailable):
        _connect()


def test_nexora_auth_routes_are_registered():
    app = FastAPI()
    register_nexora_auth_routes(app)

    paths = set(app.openapi()["paths"])
    assert "/api/v1/auth/register" in paths
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/auth/me" in paths
    assert "/api/v1/auth/logout" in paths
    assert "/api/v1/profile/tour" in paths


def test_tour_progress_payload_rejects_conflicting_terminal_states():
    with pytest.raises(ValidationError):
        TourProgressPayload.model_validate({
            "version": 1,
            "completed": True,
            "skipped": True,
            "last_step": 8,
        })


def test_tour_progress_payload_rejects_negative_step():
    with pytest.raises(ValidationError):
        TourProgressPayload.model_validate({
            "version": 1,
            "completed": False,
            "skipped": False,
            "last_step": -1,
        })
