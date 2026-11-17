"""Project-scoped creator asset ingestion routes."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile

from core.asset_registry.gltf_validator import MAX_ASSET_BYTES, validate_gltf
from core.asset_registry.registry import AssetRegistry


def register_asset_routes(app, manager_provider):
    router = APIRouter()

    @router.post("/api/projects/{pid}/assets", status_code=201)
    async def upload_project_asset(
        pid: str,
        file: UploadFile = File(...),
        kind: str = "model",
        license_name: str = "",
        source: str = "creator-upload",
        author: str = "",
    ):
        manager = manager_provider()
        try:
            folder = manager.path_for(pid)
            manager.load(pid)
        except FileNotFoundError as exc:
            raise HTTPException(404, "Project not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not license_name.strip():
            raise HTTPException(400, "An explicit asset license or rights declaration is required")
        original = (file.filename or "").replace("\\", "/").split("/")[-1]
        suffix = Path(original).suffix.lower()
        if not original or original in {".", ".."}:
            raise HTTPException(400, "A valid asset filename is required")
        if kind == "dependency":
            if suffix not in {".bin", ".png", ".jpg", ".jpeg", ".webp"}:
                raise HTTPException(400, "Dependencies must be .bin or supported image files")
        elif suffix not in {".glb", ".gltf"}:
            raise HTTPException(400, "Upload a .glb or .gltf model asset")
        if kind not in {"model", "character", "environment", "prop", "animation", "dependency"}:
            raise HTTPException(400, "Unsupported asset kind")
        asset_root = folder / "assets"
        asset_root.mkdir(parents=True, exist_ok=True)
        destination = asset_root / original
        if destination.exists():
            raise HTTPException(409, "An asset with this filename already exists in the project; rename it before upload")
        temporary = destination.with_name(destination.name + ".uploading")
        size = 0
        try:
            with temporary.open("xb") as output:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_ASSET_BYTES:
                        raise HTTPException(413, "Asset exceeds the 512 MiB upload limit")
                    output.write(chunk)
            temporary.replace(destination)
            report = (
                {"valid": True, "errors": [], "warnings": ["Dependency file is validated when its parent glTF is ingested"], "stats": {}}
                if kind == "dependency" else validate_gltf(destination)
            )
            if not report["valid"]:
                destination.unlink(missing_ok=True)
                raise HTTPException(422, {"message": "glTF validation failed", "errors": report["errors"]})
            asset_id = f"{destination.stem[:40]}-{uuid4().hex[:8]}"
            registry = AssetRegistry(asset_root)
            record = registry.register(
                asset_id=asset_id,
                relative_path=destination.name,
                kind=kind,
                license_name=license_name,
                source=source,
                author=author,
                metadata={"format": suffix[1:], "size_bytes": size, "validation": report},
            )
            return {"registered": True, "asset": record}
        except HTTPException:
            temporary.unlink(missing_ok=True)
            raise
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            raise HTTPException(400, f"Asset ingest failed: {exc}") from exc
        finally:
            await file.close()

    @router.get("/api/projects/{pid}/assets")
    def list_project_assets(pid: str):
        manager = manager_provider()
        try:
            folder = manager.path_for(pid)
            manager.load(pid)
        except FileNotFoundError as exc:
            raise HTTPException(404, "Project not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"assets": AssetRegistry(folder / "assets").list()}

    app.include_router(router)
