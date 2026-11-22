"""Shared pytest isolation for the local Foundry API integration suite.

The production cloud middleware deliberately rejects project operations. These
integration tests exercise the in-process local engine, so they bypass only the
cloud execution-location guard while retaining route handlers and validation.
"""
import pytest


@pytest.fixture(autouse=True)
def _run_integration_tests_against_local_engine(monkeypatch, request):
    if "/integration/" not in request.node.nodeid.replace("\\", "/"):
        return
    import services.api.main as api

    monkeypatch.setattr(api, "LOCAL_AGENT_MODE", False)
    monkeypatch.setattr(api, "is_local_compute_only_request", lambda method, path: False)
