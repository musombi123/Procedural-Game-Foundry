from fastapi import FastAPI

from core.nexora_workspace.desktop_api import register_desktop_factory_routes
from core.project_engine.manager import ProjectManager


def test_polyhaven_catalog_download_and_preview_routes_are_registered_once(tmp_path):
    app = FastAPI()
    register_desktop_factory_routes(app, ProjectManager(tmp_path / "projects"))

    counts = {}
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set())
        for method in methods:
            key = (method, path)
            counts[key] = counts.get(key, 0) + 1

    expected = [
        ("GET", "/api/v1/desktop/assets/3d/search"),
        ("POST", "/api/v1/desktop/projects/{pid}/assets/3d/download"),
        ("GET", "/api/v1/desktop/projects/{pid}/assets/3d/{asset_id}/file"),
    ]
    for route in expected:
        assert counts.get(route) == 1, f"Expected exactly one Poly Haven route for {route}, got {counts.get(route)}"
