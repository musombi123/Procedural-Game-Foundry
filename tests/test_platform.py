from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api import platform


def test_local_readiness_does_not_require_cloud_services(monkeypatch):
    monkeypatch.setenv("PGF_REQUIRE_CLOUD_DEPENDENCIES", "false")
    monkeypatch.setattr(platform, "_database_check", lambda: {"status": "not_configured"})
    monkeypatch.setattr(platform, "_object_storage_check", lambda: {"status": "not_configured"})

    result = platform.platform_status()

    assert result["status"] == "ready"
    assert result["mode"] == "local_or_cloud"
    assert result["required_dependencies_configured"] is False


def test_cloud_readiness_fails_closed_when_services_missing(monkeypatch):
    monkeypatch.setenv("PGF_REQUIRE_CLOUD_DEPENDENCIES", "true")
    monkeypatch.setattr(platform, "_database_check", lambda: {"status": "not_configured"})
    monkeypatch.setattr(platform, "_object_storage_check", lambda: {"status": "not_configured"})

    result = platform.platform_status()

    assert result["status"] == "not_ready"
    assert result["mode"] == "cloud"


def test_readiness_endpoint_returns_503_until_cloud_services_are_ready(monkeypatch):
    monkeypatch.setenv("PGF_REQUIRE_CLOUD_DEPENDENCIES", "true")
    monkeypatch.setattr(platform, "_database_check", lambda: {"status": "ok"})
    monkeypatch.setattr(platform, "_object_storage_check", lambda: {"status": "unavailable"})

    app = FastAPI()
    app.include_router(platform.router)
    response = TestClient(app).get("/health/ready")

    assert response.status_code == 503
    assert response.json()["detail"]["checks"]["object_storage"]["status"] == "unavailable"


def test_readiness_endpoint_returns_200_when_both_cloud_services_are_ready(monkeypatch):
    monkeypatch.setenv("PGF_REQUIRE_CLOUD_DEPENDENCIES", "true")
    monkeypatch.setattr(platform, "_database_check", lambda: {"status": "ok"})
    monkeypatch.setattr(platform, "_object_storage_check", lambda: {"status": "ok"})

    app = FastAPI()
    app.include_router(platform.router)
    response = TestClient(app).get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
