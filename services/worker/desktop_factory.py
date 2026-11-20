"""Local-first NEXORA desktop factory APIs.

These routes are mounted only by the loopback Local Agent. They never run on
the hosted control plane. All project data is rooted in the creator-selected
workspace and scoped to the paired NEXORA account.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import re
import configparser
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
SKIP_DIRS = {".git", ".godot", "__pycache__", "node_modules", ".venv"}
SKIP_FILES = {".DS_Store", "Thumbs.db"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _safe_relative(value: str) -> PurePosixPath:
    raw = str(value or "").replace("\\", "/")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise HTTPException(422, "Invalid project-relative path.")
    if any(":" in part for part in path.parts):
        raise HTTPException(422, "Drive-qualified paths are not allowed.")
    return path


class WorkspaceRequest(BaseModel):
    path: str = Field(min_length=3, max_length=1024)


class ImportRequest(BaseModel):
    path: str = Field(min_length=3, max_length=1024)
    name: str | None = Field(default=None, max_length=100)


class SaveFileRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    content: str = Field(max_length=MAX_TEXT_BYTES)
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ToolInstallRequest(BaseModel):
    tools: list[str] = Field(min_length=1, max_length=12)
    confirm_install: bool = False


class PublishRequest(BaseModel):
    platform: str = Field(pattern=r"^(web|android|windows|linux)$")
    artifact_id: str = Field(min_length=1, max_length=180)
    confirm_distribution_rights: bool = False


class ToolchainLockRequest(BaseModel):
    tools: list[str] = Field(default_factory=list, max_length=12)


class GodotBuildRequest(BaseModel):
    preset: str = Field(min_length=1, max_length=100)
    output_name: str = Field(min_length=1, max_length=120)
    mode: str = Field(default="debug", pattern=r"^(debug|release)$")


def register_desktop_factory_routes(app, require_paired, data_root: Path) -> None:
    router = APIRouter(prefix="/api/v1/desktop", tags=["NEXORA desktop factory"])
    state_root = (Path(data_root).expanduser() / "desktop-factory").resolve()
    state_root.mkdir(parents=True, exist_ok=True)

    def _owner_root(owner: str) -> Path:
        safe_owner = hashlib.sha256(str(owner).encode("utf-8")).hexdigest()[:32]
        root = (state_root / safe_owner).resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _workspace(owner: str) -> Path:
        record = _owner_root(owner) / "workspace.json"
        if not record.exists():
            raise HTTPException(409, "Choose a NEXORA projects directory first.")
        try:
            payload = json.loads(record.read_text(encoding="utf-8"))
            root = Path(payload["path"]).expanduser().resolve(strict=True)
        except (OSError, ValueError, KeyError, TypeError):
            raise HTTPException(409, "The saved workspace directory is unavailable. Select it again.")
        if not root.is_dir():
            raise HTTPException(409, "The saved workspace path is not a directory.")
        return root

    def _project(owner: str, project_id: str) -> tuple[Path, dict[str, Any]]:
        if not project_id or len(project_id) > 64:
            raise HTTPException(422, "Invalid project identifier.")
        root = _workspace(owner)
        directory = (root / project_id).resolve()
        if directory.parent != root or not directory.is_dir():
            raise HTTPException(404, "Project not found in this owner's local workspace.")
        manifest_path = directory / ".nexora" / "project.json"
        if not manifest_path.is_file():
            raise HTTPException(404, "Project has not been initialized for NEXORA.")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise HTTPException(500, "Project ownership manifest is unreadable.")
        if str(manifest.get("owner_id")) != str(owner):
            raise HTTPException(404, "Project not found in this owner's workspace.")
        return directory, manifest

    def _write_manifest(directory: Path, manifest: dict[str, Any]) -> None:
        meta = directory / ".nexora"
        meta.mkdir(parents=True, exist_ok=True)
        temp = meta / "project.json.tmp"
        temp.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        temp.replace(meta / "project.json")

    def _project_summary(directory: Path, manifest: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": manifest["id"],
            "name": manifest["name"],
            "path": str(directory),
            "created_at": manifest["created_at"],
            "updated_at": manifest.get("updated_at", manifest["created_at"]),
        }

    def _walk(directory: Path, relative: str = "") -> list[dict[str, Any]]:
        base = (directory / relative).resolve()
        if base != directory and directory not in base.parents:
            raise HTTPException(422, "Path escapes the selected project.")
        if not base.is_dir():
            raise HTTPException(404, "Project directory not found.")
        entries = []
        for item in sorted(base.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if item.name in SKIP_DIRS or item.name in SKIP_FILES or item.is_symlink():
                continue
            rel = item.relative_to(directory).as_posix()
            entries.append({
                "name": item.name,
                "path": rel,
                "kind": "directory" if item.is_dir() else "file",
                "size_bytes": item.stat().st_size if item.is_file() else 0,
            })
        return entries

    @router.get("/status")
    def status(owner: str = Depends(require_paired)):
        profile = {}
        try:
            from services.worker.system_profile import collect_system_profile
            profile = collect_system_profile(Path(data_root))
        except Exception:
            profile = {}
        root = None
        try:
            root = str(_workspace(owner))
        except HTTPException:
            pass
        projects = []
        if root:
            for child in Path(root).iterdir():
                marker = child / ".nexora" / "project.json"
                if child.is_dir() and marker.is_file():
                    try:
                        manifest = json.loads(marker.read_text(encoding="utf-8"))
                        if str(manifest.get("owner_id")) == str(owner):
                            projects.append(_project_summary(child, manifest))
                    except (OSError, ValueError, KeyError):
                        continue
        machine = profile.get("machine", {})
        return {
            "agent": {"execution_location": "creator_device", "paired": True},
            "machine": {
                "os": platform.system(),
                "logical_cpu_count": machine.get("logical_cpu_count", os.cpu_count()),
                "ram_total_gib": machine.get("ram_total_gib"),
                "disk_free_gib": machine.get("disk_free_gib"),
            },
            "workspace": root,
            "projects": len(projects),
            "project_list": projects,
        }

    @router.put("/workspace")
    def choose_workspace(payload: WorkspaceRequest, owner: str = Depends(require_paired)):
        candidate = Path(payload.path).expanduser()
        if not candidate.is_absolute():
            raise HTTPException(422, "Workspace path must be absolute.")
        candidate.mkdir(parents=True, exist_ok=True)
        root = candidate.resolve(strict=True)
        if not root.is_dir():
            raise HTTPException(422, "Workspace path must be a directory.")
        record = _owner_root(owner) / "workspace.json"
        old = None
        if record.exists():
            try:
                old = json.loads(record.read_text(encoding="utf-8")).get("path")
            except (OSError, ValueError):
                old = None
        record.write_text(json.dumps({
            "owner_id": str(owner), "path": str(root),
            "updated_at": _now(), "previous_path": old,
        }, indent=2), encoding="utf-8")
        return {"saved": True, "path": str(root), "previous_path": old, "migration": "not_performed"}

    @router.post("/projects/import")
    def import_project(payload: ImportRequest, owner: str = Depends(require_paired)):
        source = Path(payload.path).expanduser()
        if not source.is_absolute():
            raise HTTPException(422, "Import path must be absolute.")
        try:
            source = source.resolve(strict=True)
        except OSError:
            raise HTTPException(404, "Selected source folder does not exist.")
        if not source.is_dir() or not (source / "project.godot").is_file():
            raise HTTPException(422, "Select an existing Godot project folder containing project.godot.")
        root = _workspace(owner)
        project_id = str(uuid4())
        name = (payload.name or source.name).strip()[:100] or "Imported Godot Project"
        target = root / project_id
        try:
            shutil.copytree(
                source, target,
                ignore=shutil.ignore_patterns(*SKIP_DIRS, *SKIP_FILES),
                symlinks=False,
            )
            manifest = {
                "schema_version": 1, "id": project_id, "owner_id": str(owner),
                "name": name, "engine": "godot", "project_file": "project.godot",
                "created_at": _now(), "updated_at": _now(),
                "source_import": str(source), "ownership": "local_owner_account",
            }
            _write_manifest(target, manifest)
            (target / ".nexora" / "toolchain.lock.json").write_text(
                json.dumps({"schema_version": 1, "engine": "godot", "locked_at": _now(), "tools": {}}, indent=2),
                encoding="utf-8",
            )
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise
        return {"project": _project_summary(target, manifest), "imported": True, "original_unchanged": True}

    @router.post("/projects/{project_id}/initialize")
    def initialize_project(project_id: str, owner: str = Depends(require_paired)):
        directory, manifest = _project(owner, project_id)
        if not (directory / "project.godot").is_file():
            raise HTTPException(422, "This folder is not a Godot project.")
        manifest["engine"] = "godot"
        manifest["project_file"] = "project.godot"
        manifest["updated_at"] = _now()
        _write_manifest(directory, manifest)
        lock = directory / ".nexora" / "toolchain.lock.json"
        if not lock.exists():
            lock.write_text(json.dumps({"schema_version": 1, "engine": "godot", "locked_at": _now(), "tools": {}}, indent=2), encoding="utf-8")
        return {"initialized": True, "project": _project_summary(directory, manifest)}

    @router.get("/projects/{project_id}/files")
    def list_files(project_id: str, path: str = Query(default=""), owner: str = Depends(require_paired)):
        directory, _ = _project(owner, project_id)
        if path:
            rel = _safe_relative(path).as_posix()
        else:
            rel = ""
        return {"entries": _walk(directory, rel), "path": rel}

    @router.get("/projects/{project_id}/file")
    def read_file(project_id: str, path: str = Query(..., min_length=1, max_length=1024), owner: str = Depends(require_paired)):
        directory, _ = _project(owner, project_id)
        rel = _safe_relative(path)
        target = (directory / Path(*rel.parts)).resolve()
        if directory not in target.parents or target.is_symlink() or not target.is_file():
            raise HTTPException(404, "Project file not found.")
        if target.stat().st_size > MAX_TEXT_BYTES:
            raise HTTPException(413, "File is too large for the text editor.")
        try:
            content = target.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            raise HTTPException(415, "This file is binary or cannot be decoded as UTF-8.")
        return {"path": rel.as_posix(), "content": content, "sha256": _digest(target), "size_bytes": target.stat().st_size}

    @router.put("/projects/{project_id}/file")
    def save_file(project_id: str, payload: SaveFileRequest, owner: str = Depends(require_paired)):
        directory, manifest = _project(owner, project_id)
        rel = _safe_relative(payload.path)
        target = (directory / Path(*rel.parts)).resolve()
        if directory not in target.parents or target.is_symlink() or not target.is_file():
            raise HTTPException(404, "Existing project file not found.")
        if target.stat().st_size > MAX_TEXT_BYTES:
            raise HTTPException(413, "File is too large for the text editor.")
        current = _digest(target)
        if current != payload.expected_sha256:
            raise HTTPException(409, "File changed on disk. Reload before saving to avoid overwriting newer work.")
        temp = target.with_name(target.name + ".nexora-tmp")
        temp.write_text(payload.content, encoding="utf-8", newline="")
        temp.replace(target)
        manifest["updated_at"] = _now()
        _write_manifest(directory, manifest)
        return {"saved": True, "sha256": _digest(target), "size_bytes": target.stat().st_size}

    @router.get("/projects/{project_id}/snapshots")
    def list_snapshots(project_id: str, owner: str = Depends(require_paired)):
        directory, _ = _project(owner, project_id)
        snapshot_root = directory / ".nexora" / "snapshots"
        result = []
        if snapshot_root.is_dir():
            for archive in sorted(snapshot_root.glob("*.zip"), reverse=True):
                sidecar = archive.with_suffix(".json")
                try:
                    meta = json.loads(sidecar.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                result.append({**meta, "archive_bytes": archive.stat().st_size})
        return {"snapshots": result}

    @router.post("/projects/{project_id}/snapshots")
    def create_snapshot(project_id: str, owner: str = Depends(require_paired)):
        directory, manifest = _project(owner, project_id)
        snapshot_root = directory / ".nexora" / "snapshots"
        snapshot_root.mkdir(parents=True, exist_ok=True)
        snapshot_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
        archive = snapshot_root / (snapshot_id + ".zip")
        file_count = 0
        source_bytes = 0
        hashes: dict[str, str] = {}
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
            for path in directory.rglob("*"):
                if not path.is_file() or path.is_symlink():
                    continue
                relative = path.relative_to(directory)
                if any(part in SKIP_DIRS for part in relative.parts) or relative.parts[:2] == (".nexora", "snapshots"):
                    continue
                size = path.stat().st_size
                source_bytes += size
                if source_bytes > MAX_ARCHIVE_BYTES:
                    archive.unlink(missing_ok=True)
                    raise HTTPException(413, "Project exceeds the 2 GiB local snapshot limit.")
                rel = relative.as_posix()
                output.write(path, rel)
                hashes[rel] = _digest(path)
                file_count += 1
        digest = _digest(archive)
        metadata = {
            "id": snapshot_id, "file_count": file_count, "source_bytes": source_bytes,
            "archive_bytes": archive.stat().st_size, "sha256": digest,
            "created_at": _now(), "project_id": project_id, "owner_id": str(owner),
            "files": hashes,
        }
        archive.with_suffix(".json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        return metadata

    @router.post("/projects/{project_id}/snapshots/{snapshot_id}/restore")
    def restore_snapshot(project_id: str, snapshot_id: str, owner: str = Depends(require_paired)):
        directory, _ = _project(owner, project_id)
        if "/" in snapshot_id or "\\" in snapshot_id or ".." in snapshot_id:
            raise HTTPException(422, "Invalid snapshot identifier.")
        snapshot_root = directory / ".nexora" / "snapshots"
        archive = snapshot_root / (snapshot_id + ".zip")
        sidecar = archive.with_suffix(".json")
        if not archive.is_file() or not sidecar.is_file():
            raise HTTPException(404, "Snapshot not found.")
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
        if meta.get("owner_id") != str(owner) or _digest(archive) != meta.get("sha256"):
            raise HTTPException(422, "Snapshot ownership or integrity verification failed.")
        restored = 0
        with zipfile.ZipFile(archive) as source:
            for info in source.infolist():
                rel = _safe_relative(info.filename)
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise HTTPException(422, "Snapshot contains a symbolic link.")
                target = (directory / Path(*rel.parts)).resolve()
                if directory not in target.parents:
                    raise HTTPException(422, "Snapshot path escapes the project.")
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(info) as incoming, target.open("wb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing)
                expected = (meta.get("files") or {}).get(rel.as_posix())
                if expected and _digest(target) != expected:
                    raise HTTPException(422, "Restored file failed its SHA-256 integrity check.")
                restored += 1
        return {"restored": True, "files_restored": restored, "snapshot_id": snapshot_id}

    def _find_tool(candidates: list[str], env_names: tuple[str, ...] = ()) -> str | None:
        for env_name in env_names:
            value = os.environ.get(env_name)
            if value:
                candidate = Path(value).expanduser()
                if candidate.is_file():
                    return str(candidate.resolve())
                if candidate.is_dir():
                    for name in candidates:
                        direct = candidate / "bin" / name
                        if direct.is_file():
                            return str(direct.resolve())
                    for name in candidates:
                        direct = candidate / name
                        if direct.is_file():
                            return str(direct.resolve())
        for name in candidates:
            located = shutil.which(name)
            if located:
                return str(Path(located).resolve())
        return None

    def _probe(path: str | None, args: list[str], timeout: int = 8) -> dict[str, Any]:
        if not path:
            return {"available": False, "path": None, "version": None, "error": "not_found"}
        try:
            result = subprocess.run([path, *args], capture_output=True, text=True, timeout=timeout, check=False)
            output = (result.stdout or "") + "\n" + (result.stderr or "")
            first = next((line.strip() for line in output.splitlines() if line.strip()), "")
            return {"available": result.returncode == 0, "path": path, "version": first[:240], "exit_code": result.returncode}
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"available": False, "path": path, "version": None, "error": type(exc).__name__}

    def _tool_inventory() -> dict[str, dict[str, Any]]:
        sdk_root = os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
        if not sdk_root and os.environ.get("LOCALAPPDATA"):
            sdk_root = str(Path(os.environ["LOCALAPPDATA"]) / "Android" / "Sdk")
        sdk = Path(sdk_root).expanduser() if sdk_root else None
        godot_path = _find_tool(["godot", "godot.exe", "godot4", "godot4.exe"], ("NEXORA_GODOT_PATH",))
        blender_path = _find_tool(["blender", "blender.exe"], ("NEXORA_BLENDER_PATH",))
        ffmpeg_path = _find_tool(["ffmpeg", "ffmpeg.exe"], ("NEXORA_FFMPEG_PATH",))
        java_path = _find_tool(["java", "java.exe"], ("JAVA_HOME",))
        sdkmanager_candidates = []
        if sdk:
            sdkmanager_candidates += [str(sdk / "cmdline-tools" / "latest" / "bin" / name) for name in ("sdkmanager.bat", "sdkmanager")]
            sdkmanager_candidates += [str(sdk / "tools" / "bin" / name) for name in ("sdkmanager.bat", "sdkmanager")]
        sdkmanager_path = next((p for p in sdkmanager_candidates if Path(p).is_file()), None) or _find_tool(["sdkmanager", "sdkmanager.bat"])
        adb_path = str(sdk / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb")) if sdk else None
        if not adb_path or not Path(adb_path).is_file():
            adb_path = _find_tool(["adb", "adb.exe"])
        return {
            "godot4": _probe(godot_path, ["--version"]),
            "blender": _probe(blender_path, ["--version"]),
            "ffmpeg": _probe(ffmpeg_path, ["-version"]),
            "java": _probe(java_path, ["-version"]),
            "sdkmanager": _probe(sdkmanager_path, ["--version"]),
            "adb": _probe(adb_path, ["version"]),
            "android_sdk": {"available": bool(sdk and sdk.is_dir()), "path": str(sdk.resolve()) if sdk and sdk.is_dir() else None, "version": None},
        }

    @router.get("/toolchains")
    def toolchains(owner: str = Depends(require_paired)):
        catalog = [
            {"id":"godot4","label":"Godot 4","purpose":"Game engine and matching export templates","required_for":["web","android","windows"]},
            {"id":"blender","label":"Blender","purpose":"Optional 3D asset creation and processing"},
            {"id":"ffmpeg","label":"FFmpeg","purpose":"Optional audio/video conversion"},
            {"id":"java","label":"OpenJDK 17","purpose":"Android export toolchain"},
            {"id":"android_sdk","label":"Android SDK","purpose":"Android APK/AAB export"},
            {"id":"adb","label":"Android Platform Tools","purpose":"Optional physical-device testing"},
            {"id":"sdkmanager","label":"Android SDK Manager","purpose":"Install pinned Android SDK components"},
        ]
        tools = _tool_inventory()
        profile = {}
        try:
            from services.worker.system_profile import collect_system_profile
            profile = collect_system_profile(Path(data_root))
        except Exception:
            pass
        return {"machine":{"system":platform.system()},"install_provider":"android_sdkmanager_only","catalog":catalog,"tools":tools,"lock":None,"profile":profile,
                "android_export_ready": bool(tools["java"]["available"] and tools["android_sdk"]["available"] and tools["godot4"]["available"])}

    @router.post("/toolchains/install")
    def install_toolchains(payload: ToolInstallRequest, owner: str = Depends(require_paired)):
        if not payload.confirm_install:
            raise HTTPException(403, "Explicitly confirm installation on this computer.")
        if set(payload.tools) != {"android_sdk"}:
            raise HTTPException(422, "Only Android SDK components can currently be installed by NEXORA. Install Godot, Java, Blender and FFmpeg from their official distributors.")
        inventory = _tool_inventory()
        manager = inventory["sdkmanager"]
        sdk_root = inventory["android_sdk"]["path"] or os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
        if not manager["available"] or not manager["path"]:
            raise HTTPException(409, "Android sdkmanager was not found. Install Android command-line tools from the official Android developer site first.")
        if not sdk_root:
            raise HTTPException(409, "Set ANDROID_SDK_ROOT or ANDROID_HOME to the SDK directory before installing components.")
        # Fixed, reviewed package IDs; callers cannot pass arbitrary package names or shell arguments.
        packages = ["platform-tools", "build-tools;35.0.1", "platforms;android-35", "cmdline-tools;latest", "cmake;3.10.2.4988404", "ndk;28.1.13356709"]
        command = [manager["path"], "--sdk_root=" + str(Path(sdk_root).resolve()), *packages]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=3600, check=False)
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "Android SDK installation exceeded the one-hour limit.")
        except OSError as exc:
            raise HTTPException(500, "Could not start Android SDK Manager: " + type(exc).__name__)
        output = ((result.stdout or "") + "\n" + (result.stderr or ""))[-5000:]
        if result.returncode != 0:
            raise HTTPException(409, "SDK Manager did not complete. Review the local output; Android SDK licence acceptance may be required first. " + output[-1200:])
        return {"installed":True,"provider":"sdkmanager","sdk_root":str(Path(sdk_root).resolve()),"packages":packages,"output":output}
    
    @router.post("/projects/{project_id}/toolchains/lock")
    def lock_toolchains(project_id: str, payload: ToolchainLockRequest, owner: str = Depends(require_paired)):
        directory, manifest = _project(owner, project_id)
        inventory = _tool_inventory()
        allowed = {"godot4","blender","ffmpeg","java","android_sdk","adb","sdkmanager"}
        unknown = sorted(set(payload.tools) - allowed)
        if unknown:
            raise HTTPException(422, "Unknown toolchain IDs: " + ", ".join(unknown))
        missing = [name for name in payload.tools if not inventory.get(name, {}).get("available")]
        if missing:
            raise HTTPException(409, "Cannot lock unavailable tools: " + ", ".join(missing))
        lock = {"schema_version":1,"engine":"godot","locked_at":_now(),"tools":{name:inventory[name] for name in payload.tools}}
        target = directory / ".nexora" / "toolchain.lock.json"
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(lock,indent=2,sort_keys=True),encoding="utf-8")
        manifest["updated_at"] = _now()
        _write_manifest(directory,manifest)
        return {"locked":True,"lock":lock}
    
    @router.post("/projects/{project_id}/validate")
    def validate_godot_project(project_id: str, owner: str = Depends(require_paired)):
        directory, _ = _project(owner, project_id)
        project_file = directory / "project.godot"
        if not project_file.is_file():
            raise HTTPException(422, "project.godot is missing.")
        godot = _tool_inventory()["godot4"]
        if not godot["available"] or not godot["path"]:
            raise HTTPException(409, "Godot 4 editor binary was not detected on this computer.")
        try:
            result = subprocess.run([godot["path"], "--headless", "--path", str(directory), "--editor", "--quit"],capture_output=True,text=True,timeout=180,check=False)
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "Godot project validation exceeded 180 seconds.")
        except OSError as exc:
            raise HTTPException(500, "Could not start Godot: " + type(exc).__name__)
        output = ((result.stdout or "") + "\n" + (result.stderr or ""))[-12000:]
        return {"valid":result.returncode == 0,"exit_code":result.returncode,"engine":godot["version"],"output":output}
    
    @router.post("/projects/{project_id}/build")
    def build_godot_project(project_id: str, payload: GodotBuildRequest, owner: str = Depends(require_paired)):
        directory, _ = _project(owner, project_id)
        preset_file = directory / "export_presets.cfg"
        if not preset_file.is_file():
            raise HTTPException(409, "Create an export preset in Godot before building with NEXORA.")
        preset_text = preset_file.read_text(encoding="utf-8",errors="replace")
        sections = re.findall(r'^\[preset\.\d+\]\s*\n([\s\S]*?)(?=^\[|\Z)',preset_text,re.MULTILINE)
        names = []
        for section in sections:
            match = re.search(r'^name="([^"]+)"\s*
    @router.get("/publish/readiness")
    def publish_readiness(owner: str = Depends(require_paired)):
        return {"publishers":[
            {"id":"google_play","name":"Google Play","ready":False,"missing":["Creator-owned Play Console app and publisher credentials are not connected."]},
            {"id":"apple","name":"Apple App Store","ready":False,"missing":["A macOS/Xcode build relay and App Store Connect credentials are required."]},
            {"id":"microsoft","name":"Microsoft Store","ready":False,"missing":["MSIX signing and Partner Center app identity are not configured."]},
        ]}

    @router.get("/drive/status")
    def drive_status(owner: str = Depends(require_paired)):
        return {"connected":False,"configured":False,"credential_vault_ready":False,"provider":"google_drive","scope":"drive.file"}

    @router.post("/drive/authorize")
    def drive_authorize(owner: str = Depends(require_paired)):
        raise HTTPException(501, "Google Drive OAuth is not configured. Add a verified desktop OAuth client and OS credential-vault integration first.")

    @router.post("/drive/disconnect")
    def drive_disconnect(owner: str = Depends(require_paired)):
        return {"disconnected":True}

    @router.get("/drive/projects/{project_id}/backups")
    def drive_backups(project_id: str, owner: str = Depends(require_paired)):
        _project(owner, project_id)
        return {"files":[]}

    @router.post("/projects/{project_id}/publish/prepare")
    def prepare_publish(project_id: str, payload: PublishRequest, owner: str = Depends(require_paired)):
        directory, manifest = _project(owner, project_id)
        if not payload.confirm_distribution_rights:
            raise HTTPException(403, "Confirm that you own or have distribution rights for every included asset.")
        artifact = Path(payload.artifact_id).expanduser()
        if not artifact.is_absolute():
            artifact = directory / artifact
        artifact = artifact.resolve()
        if not artifact.is_file():
            raise HTTPException(404, "Build artifact was not found on this computer.")
        if artifact.stat().st_size <= 0:
            raise HTTPException(422, "Build artifact is empty.")
        digest = _digest(artifact)
        release_root = directory / ".nexora" / "releases"
        release_root.mkdir(parents=True, exist_ok=True)
        release_id = str(uuid4())
        record = {
            "schema_version":1,"release_id":release_id,"project_id":project_id,
            "owner_id":str(owner),"platform":payload.platform,"artifact_path":str(artifact),
            "artifact_size_bytes":artifact.stat().st_size,"sha256":digest,
            "project_name":manifest["name"],"distribution_rights_confirmed":True,
            "created_at":_now(),"status":"prepared_not_uploaded",
        }
        (release_root / (release_id + ".json")).write_text(json.dumps(record,indent=2),encoding="utf-8")
        return {"prepared":True,"release":record,"uploaded":False,"submitted":False}

    app.include_router(router)
,section,re.MULTILINE)
            if match:
                names.append(match.group(1))
        if payload.preset not in names:
            raise HTTPException(422, "Requested export preset does not exist in export_presets.cfg.")
        godot = _tool_inventory()["godot4"]
        if not godot["available"] or not godot["path"]:
            raise HTTPException(409, "Godot 4 editor binary was not detected on this computer.")
        if Path(payload.output_name).name != payload.output_name or payload.output_name in {".",".."}:
            raise HTTPException(422, "Output name must be a filename, not a path.")
        ext = {"Windows Desktop":".exe","Windows":".exe","Android":".apk","Web":".zip","Linux/X11":".x86_64"}
        suffix = Path(payload.output_name).suffix.lower()
        if not suffix:
            suffix = ext.get(payload.preset,".bin")
        if payload.preset == "Android" and suffix not in {".apk",".aab"}:
            raise HTTPException(422, "Android output must be .apk or .aab.")
        if payload.preset == "Web" and suffix != ".zip":
            raise HTTPException(422, "Web export output must be a .zip bundle.")
        output_root = directory / "exports" / re.sub(r'[^a-z0-9_-]+','-',payload.preset.lower()).strip("-")
        output_root.mkdir(parents=True,exist_ok=True)
        output = output_root / (payload.output_name if Path(payload.output_name).suffix else payload.output_name + suffix)
        command = [godot["path"],"--headless","--path",str(directory),"--export-debug" if payload.mode == "debug" else "--export-release",payload.preset,str(output)]
        try:
            result = subprocess.run(command,capture_output=True,text=True,timeout=1800,check=False)
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "Godot export exceeded the 30-minute limit.")
        except OSError as exc:
            raise HTTPException(500, "Could not start Godot export: " + type(exc).__name__)
        output_text = ((result.stdout or "") + "\n" + (result.stderr or ""))[-16000:]
        if result.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
            return {"built":False,"exit_code":result.returncode,"output":output_text,"artifact":None}
        return {"built":True,"exit_code":0,"output":output_text,"artifact":{"path":str(output),"size_bytes":output.stat().st_size,"sha256":_digest(output),"platform_preset":payload.preset,"mode":payload.mode}}

    @router.get("/publish/readiness")
    def publish_readiness(owner: str = Depends(require_paired)):
        return {"publishers":[
            {"id":"google_play","name":"Google Play","ready":False,"missing":["Creator-owned Play Console app and publisher credentials are not connected."]},
            {"id":"apple","name":"Apple App Store","ready":False,"missing":["A macOS/Xcode build relay and App Store Connect credentials are required."]},
            {"id":"microsoft","name":"Microsoft Store","ready":False,"missing":["MSIX signing and Partner Center app identity are not configured."]},
        ]}

    @router.get("/drive/status")
    def drive_status(owner: str = Depends(require_paired)):
        return {"connected":False,"configured":False,"credential_vault_ready":False,"provider":"google_drive","scope":"drive.file"}

    @router.post("/drive/authorize")
    def drive_authorize(owner: str = Depends(require_paired)):
        raise HTTPException(501, "Google Drive OAuth is not configured. Add a verified desktop OAuth client and OS credential-vault integration first.")

    @router.post("/drive/disconnect")
    def drive_disconnect(owner: str = Depends(require_paired)):
        return {"disconnected":True}

    @router.get("/drive/projects/{project_id}/backups")
    def drive_backups(project_id: str, owner: str = Depends(require_paired)):
        _project(owner, project_id)
        return {"files":[]}

    @router.post("/projects/{project_id}/publish/prepare")
    def prepare_publish(project_id: str, payload: PublishRequest, owner: str = Depends(require_paired)):
        directory, manifest = _project(owner, project_id)
        if not payload.confirm_distribution_rights:
            raise HTTPException(403, "Confirm that you own or have distribution rights for every included asset.")
        artifact = Path(payload.artifact_id).expanduser()
        if not artifact.is_absolute():
            artifact = directory / artifact
        artifact = artifact.resolve()
        if not artifact.is_file():
            raise HTTPException(404, "Build artifact was not found on this computer.")
        if artifact.stat().st_size <= 0:
            raise HTTPException(422, "Build artifact is empty.")
        digest = _digest(artifact)
        release_root = directory / ".nexora" / "releases"
        release_root.mkdir(parents=True, exist_ok=True)
        release_id = str(uuid4())
        record = {
            "schema_version":1,"release_id":release_id,"project_id":project_id,
            "owner_id":str(owner),"platform":payload.platform,"artifact_path":str(artifact),
            "artifact_size_bytes":artifact.stat().st_size,"sha256":digest,
            "project_name":manifest["name"],"distribution_rights_confirmed":True,
            "created_at":_now(),"status":"prepared_not_uploaded",
        }
        (release_root / (release_id + ".json")).write_text(json.dumps(record,indent=2),encoding="utf-8")
        return {"prepared":True,"release":record,"uploaded":False,"submitted":False}

    app.include_router(router)
