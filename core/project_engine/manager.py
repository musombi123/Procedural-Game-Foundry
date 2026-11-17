from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4
import hashlib
import json

from .models import ProjectCreate, ProjectDefinition, WorldDocument, safe_slug


class ProjectManager:
    """Persistent local project store with immutable, content-addressed revisions."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def path_for(self, pid: str) -> Path:
        if not pid or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in pid):
            raise ValueError("Invalid project id")
        path = (self.root / pid).resolve()
        if self.root not in path.parents:
            raise ValueError("Project path escapes workspace")
        return path

    def create(self, request: ProjectCreate) -> ProjectDefinition:
        pid = f"{safe_slug(request.name)}-{uuid4().hex[:8]}"
        definition = ProjectDefinition(id=pid, project=request)
        folder = self.path_for(pid)
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "pgf.json").write_text(definition.model_dump_json(indent=2), encoding="utf-8")
        for name in ("assets", "generated", "versions"):
            (folder / name).mkdir()
        initial_world = WorldDocument(seed=request.seed, world=definition.world)
        self.save_world(pid, initial_world, reason="project-created")
        return definition

    def load(self, pid: str) -> ProjectDefinition:
        file = self.path_for(pid) / "pgf.json"
        if not file.is_file():
            raise FileNotFoundError(pid)
        return ProjectDefinition.model_validate_json(file.read_text(encoding="utf-8"))

    def list(self):
        result = []
        for file in self.root.glob("*/pgf.json"):
            try:
                result.append(ProjectDefinition.model_validate_json(file.read_text(encoding="utf-8")))
            except Exception:
                continue
        return result

    def save_world(self, pid: str, document: WorldDocument, reason: str = "autosave", actor_id: str | None = None) -> dict:
        folder = self.path_for(pid)
        if not (folder / "pgf.json").is_file():
            raise FileNotFoundError(pid)
        world_json = document.model_dump(mode="json")
        project_json = json.loads((folder / "pgf.json").read_text(encoding="utf-8"))
        payload = {"project": project_json, "world": world_json}
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        checksum = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        versions = folder / "versions"
        versions.mkdir(exist_ok=True)
        with self._lock:
            existing = sorted(versions.glob("*.json"))
            if existing:
                latest = json.loads(existing[-1].read_text(encoding="utf-8"))
                if latest.get("checksum") == checksum:
                    return {"saved": True, "revision": latest["revision"], "checksum": checksum, "unchanged": True}
            revision = (int(existing[-1].stem) + 1) if existing else 1
            record = {
                "revision": revision,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "reason": reason[:40],
                "actor_id": actor_id,
                "checksum": checksum,
                **payload,
            }
            target = versions / f"{revision:08d}.json"
            temporary = target.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(record, indent=2), encoding="utf-8")
            temporary.replace(target)
            world_path = folder / "world.json"
            world_tmp = world_path.with_suffix(".json.tmp")
            world_tmp.write_text(document.model_dump_json(indent=2), encoding="utf-8")
            world_tmp.replace(world_path)
            return {"saved": True, "revision": revision, "checksum": checksum, "unchanged": False}

    def list_versions(self, pid: str) -> list[dict]:
        folder = self.path_for(pid)
        if not (folder / "pgf.json").is_file():
            raise FileNotFoundError(pid)
        versions = folder / "versions"
        if not versions.is_dir():
            return []
        result = []
        for file in sorted(versions.glob("*.json"), reverse=True):
            try:
                record = json.loads(file.read_text(encoding="utf-8"))
                result.append({key: record[key] for key in ("revision", "created_at", "reason", "actor_id", "checksum")})
            except (OSError, ValueError, KeyError):
                continue
        return result

    def restore_version(self, pid: str, revision: int, actor_id: str | None = None) -> dict:
        folder = self.path_for(pid)
        if revision < 1:
            raise ValueError("Revision must be positive")
        source = folder / "versions" / f"{revision:08d}.json"
        if not source.is_file():
            raise FileNotFoundError(f"Revision {revision} not found")
        record = json.loads(source.read_text(encoding="utf-8"))
        project = ProjectDefinition.model_validate(record["project"])
        world = WorldDocument.model_validate(record["world"])
        project_tmp = folder / "pgf.json.tmp"
        project_tmp.write_text(project.model_dump_json(indent=2), encoding="utf-8")
        project_tmp.replace(folder / "pgf.json")
        result = self.save_world(pid, world, reason=f"restore:{revision}", actor_id=actor_id)
        return {"restored_from": revision, **result}
