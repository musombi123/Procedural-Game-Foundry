from fastapi import FastAPI

from core.nexora_workspace.desktop_api import register_desktop_factory_routes
from core.project_engine.manager import ProjectManager


def test_polyhaven_catalog_download_and_preview_routes_are_exposed(tmp_path):
    app = FastAPI()
    register_desktop_factory_routes(app, ProjectManager(tmp_path / "projects"))

    # FastAPI's newer router implementation includes routers lazily; app.routes
    # can contain an _IncludedRouter rather than flattened APIRoute entries.
    # OpenAPI is the stable, public view of the effective HTTP route table.
    paths = app.openapi()["paths"]
    expected = {
        ("/api/v1/desktop/assets/3d/search", "get"),
        ("/api/v1/desktop/projects/{pid}/assets/3d/download", "post"),
        ("/api/v1/desktop/projects/{pid}/assets/3d/{asset_id}/file", "get"),
    }
    registered = {
        (path, method.lower())
        for path, operations in paths.items()
        for method in operations
    }

    for route in expected:
        assert route in registered, f"Expected the Poly Haven route to be exposed: {route}"
