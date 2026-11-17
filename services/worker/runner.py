"""NEXORA local/dedicated build worker.

The API process never runs Blender, Godot or Android SDK tasks. This runner claims
PostgreSQL jobs with SKIP LOCKED leases and executes them on a worker host where
Blender/Godot/export templates are installed.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from core.game_assembler.godot import assemble_godot_project
from core.game_assembler.workspace_adapter import build_documents
from services.storage.postgres import database, ensure_schema
from services.storage import object_store


WORKER_ID = os.getenv("PGF_WORKER_ID", f"worker-{uuid4().hex[:10]}")


def _executable(env_name: str, default: str) -> str | None:
    configured = os.getenv(env_name, "").strip()
    return configured if configured and Path(configured).exists() else shutil.which(default)


def _run(command: list[str], timeout: int = 1800) -> dict[str, Any]:
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    output = (result.stdout or "")[-12000:]
    errors = (result.stderr or "")[-12000:]
    if result.returncode != 0:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(command[:4])}\n{errors or output}")
    return {"returncode": result.returncode, "stdout": output, "stderr": errors}


def claim_job() -> dict[str, Any] | None:
    with database() as connection:
        ensure_schema(connection)
        row = connection.execute(
            """
            SELECT * FROM nexora_jobs
            WHERE state = 'queued'
               OR (state = 'running' AND lease_expires_at < now())
            ORDER BY created_at
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """
        ).fetchone()
        if not row:
            return None
        updated = connection.execute(
            """
            UPDATE nexora_jobs SET state='running', worker_id=%s,
                lease_expires_at=now() + interval '4 hours',
                progress=5, message='Claimed by NEXORA worker', updated_at=now()
            WHERE id=%s
            RETURNING *
            """,
            (WORKER_ID, row["id"]),
        ).fetchone()
        return updated


def update_job(job_id, progress: int, message: str) -> None:
    with database() as connection:
        connection.execute(
            "UPDATE nexora_jobs SET progress=%s, message=%s, updated_at=now() WHERE id=%s AND worker_id=%s",
            (max(0, min(99, progress)), message[:500], job_id, WORKER_ID),
        )


def finish_job(job_id, result: dict[str, Any]) -> None:
    with database() as connection:
        connection.execute(
            "UPDATE nexora_jobs SET state='completed', progress=100, message='Production job completed', result=%s, error=NULL, lease_expires_at=NULL, updated_at=now() WHERE id=%s AND worker_id=%s",
            (Jsonb(result), job_id, WORKER_ID),
        )


def fail_job(job: dict[str, Any], exc: Exception) -> None:
    with database() as connection:
        connection.execute(
            "UPDATE nexora_jobs SET state='failed', message='Production job failed', error=%s, lease_expires_at=NULL, updated_at=now() WHERE id=%s AND worker_id=%s",
            (str(exc)[-12000:], job["id"], WORKER_ID),
        )
        if job["kind"] == "asset.process":
            asset_id = (job.get("payload") or {}).get("asset_id")
            if asset_id:
                connection.execute(
                    "UPDATE nexora_assets SET status='failed' WHERE id=%s AND owner_id=%s",
                    (asset_id, job["owner_id"]),
                )


def _artifact(job: dict[str, Any], path: Path, filename: str, content_type: str) -> dict[str, Any]:
    artifact_id = uuid4()
    key = f"nexora-artifacts/{job['owner_id']}/{job['id']}/{artifact_id}/{filename}"
    object_store.upload_file(path, key, content_type)
    size = path.stat().st_size
    with database() as connection:
        connection.execute(
            "INSERT INTO nexora_artifacts (id, job_id, owner_id, object_key, filename, content_type, size) VALUES (%s,%s,%s,%s,%s,%s)",
            (artifact_id, job["id"], job["owner_id"], key, filename, content_type, size),
        )
    return {"id": str(artifact_id), "filename": filename, "size": size, "content_type": content_type}


def _project_from_job(job: dict[str, Any], workdir: Path):
    payload = job.get("payload") or {}
    source = payload.get("project") or {}
    target = workdir / "game"
    asset_directory = target / "assets"
    asset_directory.mkdir(parents=True, exist_ok=True)
    asset_paths: dict[str, str] = {}

    # Only server-selected, owner-scoped GLBs from the queued job are copied into
    # the project. Filenames are generated from UUIDs; user filenames never form
    # an output path and cannot escape the build directory.
    for asset in payload.get("assets") or []:
        try:
            asset_id = str(UUID(str(asset.get("id") or "")))
        except ValueError:
            continue
        if not str(asset.get("filename") or "").lower().endswith(".glb"):
            continue
        object_key = str(asset.get("object_key") or "")
        if not object_key or not object_key.startswith("owners/"):
            raise RuntimeError("A creator asset has an invalid private object key.")
        destination = asset_directory / f"{asset_id}.glb"
        object_store.download_file(object_key, destination)
        if not destination.is_file() or destination.stat().st_size < 20:
            raise RuntimeError(f"Creator asset {asset_id} is empty or invalid.")
        asset_paths[asset_id] = f"res://assets/{asset_id}.glb"

    definition, world = build_documents(str(job["project_id"]), source, asset_paths)
    assemble_godot_project(definition, target, world.model_dump(mode="json"))
    _write_export_presets(target)
    return target


def _write_export_presets(project: Path) -> None:
    text = """[preset.0]
name="Linux/X11"
platform="Linux/X11"
runnable=true
dedicated_server=false
custom_features=""
export_filter="all_resources"
include_filter=""
exclude_filter=""
export_path="build/linux/NexoraFoundry.x86_64"
encryption_include_filters=""
encryption_exclude_filters=""
encrypt_pck=false
encrypt_directory=false

[preset.0.options]
custom_template/debug=""
custom_template/release=""
debug/export_console_wrapper=0
binary_format/64_bits=true
binary_format/embed_pck=false
texture_format/bptc=false
texture_format/s3tc=true
texture_format/etc2=true

[preset.1]
name="Windows Desktop"
platform="Windows Desktop"
runnable=true
dedicated_server=false
custom_features=""
export_filter="all_resources"
include_filter=""
exclude_filter=""
export_path="build/windows/NexoraFoundry.exe"
encryption_include_filters=""
encryption_exclude_filters=""
encrypt_pck=false
encrypt_directory=false

[preset.1.options]
custom_template/debug=""
custom_template/release=""
debug/export_console_wrapper=0
binary_format/64_bits=true
binary_format/embed_pck=false
texture_format/bptc=false
texture_format/s3tc=true
texture_format/etc2=true

[preset.2]
name="Android"
platform="Android"
runnable=true
dedicated_server=false
custom_features=""
export_filter="all_resources"
include_filter=""
exclude_filter=""
export_path="build/android/NexoraFoundry-debug.apk"
encryption_include_filters=""
encryption_exclude_filters=""
encrypt_pck=false
encrypt_directory=false

[preset.2.options]
custom_template/debug=""
custom_template/release=""
gradle_build/use_gradle_build=false
gradle_build/export_format=0
architectures/armeabi-v7a=false
architectures/arm64-v8a=true
package/unique_name="com.nexora.foundry"
package/name="Nexora Foundry"
package/signed=true
version/code=1
version/name="1.0.0"
screen/immersive_mode=true
permissions/internet=true
"""
    (project / "export_presets.cfg").write_text(text, encoding="utf-8")


def _zip_folder(folder: Path, output: Path) -> None:
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in folder.rglob("*"):
            if file.is_file() and file != output:
                archive.write(file, file.relative_to(folder))


def _run_asset_process(job: dict[str, Any], workdir: Path) -> dict[str, Any]:
    blender = _executable("BLENDER_BIN", "blender")
    if not blender:
        raise RuntimeError("Blender is not installed on this worker (set BLENDER_BIN or add blender to PATH).")
    payload = job["payload"]
    asset_id = payload["asset_id"]
    with database() as connection:
        asset = connection.execute(
            "SELECT * FROM nexora_assets WHERE id=%s AND owner_id=%s",
            (asset_id, job["owner_id"]),
        ).fetchone()
    if not asset:
        raise RuntimeError("Source asset record no longer exists.")
    source = workdir / asset["filename"]
    normalized = workdir / "normalized.glb"
    report = workdir / "asset-report.json"
    object_store.download_file(asset["object_key"], source)
    script = Path(__file__).resolve().parents[2] / "blender" / "scripts" / "process_creator_asset.py"
    _run([blender, "--background", "--python", str(script), "--", "--input", str(source), "--output", str(normalized), "--report", str(report)], timeout=900)
    report_data = json.loads(report.read_text(encoding="utf-8"))
    key = f"{asset['object_key']}.normalized.glb"
    object_store.upload_file(normalized, key, "model/gltf-binary")
    with database() as connection:
        connection.execute(
            "UPDATE nexora_assets SET status='processed', processed_object_key=%s, size=%s WHERE id=%s AND owner_id=%s",
            (key, normalized.stat().st_size, asset_id, job["owner_id"]),
        )
    artifact = _artifact(job, report, f"{asset['filename']}.report.json", "application/json")
    return {"processor": "Blender", "asset_id": asset_id, "normalized_object": key, "report": report_data, "artifacts": [artifact]}


def _verify_runtime(project: Path, godot: str) -> dict[str, Any]:
    runtime = _run(
        [godot, "--headless", "--path", str(project), "--quit-after", "120"],
        timeout=180,
    )
    output = f"{runtime.get('stdout', '')}\\n{runtime.get('stderr', '')}"
    if "SCRIPT ERROR:" in output or "Parse Error" in output:
        raise RuntimeError(f"Generated Godot gameplay scene failed its runtime smoke test:\\n{output[-6000:]}")
    return runtime


def _run_scene_generation(job: dict[str, Any], workdir: Path) -> dict[str, Any]:
    godot = _executable("GODOT_BIN", "godot")
    if not godot:
        raise RuntimeError("Godot 4 is not installed on this worker (set GODOT_BIN or add godot to PATH).")
    project = _project_from_job(job, workdir)
    check = _run([godot, "--headless", "--path", str(project), "--editor", "--quit"], timeout=600)
    required = [project / "project.godot", project / "main.tscn", project / "scripts" / "main.gd"]
    if not all(path.is_file() for path in required):
        raise RuntimeError("Generated Godot project is missing required scene files.")
    runtime = _verify_runtime(project, godot)
    archive = workdir / "nexora-godot-project.zip"
    _zip_folder(project, archive)
    artifact = _artifact(job, archive, "nexora-godot-project.zip", "application/zip")
    return {"engine": "Godot 4", "scene_generated": True, "headless_editor_check": check, "headless_runtime_smoke": runtime, "artifacts": [artifact]}


def _run_build_export(job: dict[str, Any], workdir: Path) -> dict[str, Any]:
    godot = _executable("GODOT_BIN", "godot")
    if not godot:
        raise RuntimeError("Godot 4 is not installed on this worker (set GODOT_BIN or add godot to PATH).")
    project = _project_from_job(job, workdir)
    check = _run([godot, "--headless", "--path", str(project), "--editor", "--quit"], timeout=600)
    runtime = _verify_runtime(project, godot)
    target = (job.get("payload") or {}).get("target", "desktop")
    requested = {"desktop": ["Linux/X11", "Windows Desktop"], "android": ["Android"], "desktop_android": ["Linux/X11", "Windows Desktop", "Android"]}.get(target)
    if not requested:
        raise RuntimeError("Unsupported export target.")
    outputs = {
        "Linux/X11": project / "build" / "linux" / "NexoraFoundry.x86_64",
        "Windows Desktop": project / "build" / "windows" / "NexoraFoundry.exe",
        "Android": project / "build" / "android" / "NexoraFoundry-debug.apk",
    }
    export_results = []
    for preset in requested:
        output = outputs[preset]
        output.parent.mkdir(parents=True, exist_ok=True)
        mode = "--export-debug" if preset == "Android" else "--export-release"
        export_results.append({"preset": preset, **_run([godot, "--headless", "--path", str(project), mode, preset, str(output)], timeout=2400)})
        if not output.is_file() or output.stat().st_size < 1024:
            raise RuntimeError(f"{preset} export did not produce a valid artifact.")
    archive = workdir / "nexora-builds.zip"
    _zip_folder(project / "build", archive)
    artifact = _artifact(job, archive, "nexora-builds.zip", "application/zip")
    return {"engine": "Godot 4", "headless_editor_check": check, "headless_runtime_smoke": runtime, "exports": export_results, "artifacts": [artifact], "release_type": "development/debug; production signing and approval remain separate"}


def process(job: dict[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="nexora-worker-") as directory:
        workdir = Path(directory)
        update_job(job["id"], 20, f"Running {job['kind']} task")
        if job["kind"] == "asset.process":
            return _run_asset_process(job, workdir)
        if job["kind"] == "scene.generate":
            return _run_scene_generation(job, workdir)
        if job["kind"] == "build.export":
            return _run_build_export(job, workdir)
        raise RuntimeError(f"Unsupported job kind: {job['kind']}")


def main() -> None:
    if not os.getenv("DATABASE_URL"):
        raise SystemExit("DATABASE_URL is required for the NEXORA worker.")
    if not object_store.configured():
        raise SystemExit("NEXORA private object storage credentials are required for the worker.")
    poll_seconds = max(2, int(os.getenv("PGF_WORKER_POLL_SECONDS", "5")))
    print(f"NEXORA worker {WORKER_ID} started; poll={poll_seconds}s")
    while True:
        job = None
        try:
            job = claim_job()
            if not job:
                time.sleep(poll_seconds)
                continue
            print(f"Claimed job {job['id']} ({job['kind']})")
            try:
                result = process(job)
                finish_job(job["id"], result)
            except Exception as exc:
                print(f"Job {job['id']} failed: {exc}")
                fail_job(job, exc)
        except KeyboardInterrupt:
            print("NEXORA worker stopping.")
            return
        except Exception as exc:
            print(f"Worker loop error: {exc}")
            time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
