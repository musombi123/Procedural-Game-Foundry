import asyncio
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Request
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from core.project_engine.models import ProjectCreate, WorldDocument
from core.project_engine.manager import ProjectManager
from core.orchestration.jobs import Job, JobRegistry, JobState
from core.game_assembler.godot import assemble_godot_project
from core.validation.validator import validate_project
from core.build_engine.godot_cli import headless_check
from core.nexora_workspace.identity import (
    NexoraIdentityUnavailable,
    register_nexora_auth_routes,
    verify_access_token,
)
from core.execution_policy import is_local_compute_only_request, local_compute_block_payload
from services.worker.local_security import verify_local_access_token
from services.worker.workload_guard import require_device_profile

# Render is always a hosted control plane. Even an accidental environment
# variable must never promote the cloud process into a local compute worker.
_LOCAL_AGENT_REQUESTED = os.environ.get("NEXORA_LOCAL_AGENT", "false").strip().lower() in {"1", "true", "yes"}
LOCAL_AGENT_MODE = _LOCAL_AGENT_REQUESTED and not bool(os.environ.get("RENDER"))

DATA = Path(os.environ.get("PGF_DATA_DIR", ".pgf-data")).resolve()
manager = ProjectManager(DATA / "projects")
jobs = JobRegistry()
app = FastAPI(title="Procedural Game Foundry API", version="0.2.0", description="Model-free local-first game creation service")
_default_auth_required = bool(os.environ.get("RENDER")) or os.environ.get("NEXORA_ENV", "").lower() == "production"
AUTH_REQUIRED = os.environ.get("NEXORA_AUTH_REQUIRED", "true" if _default_auth_required else "false").lower() in {"1", "true", "yes"}
os.environ["NEXORA_AUTH_REQUIRED"] = "true" if AUTH_REQUIRED else "false"

_origins = [item.strip() for item in os.environ.get("NEXORA_CORS_ORIGINS", "https://revelacode.co.ke,http://localhost:5174,http://127.0.0.1:5174,tauri://localhost").split(",") if item.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_credentials=True, allow_methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"], allow_headers=["Authorization","Content-Type","Accept","X-Revela-License","X-Nexora-Payment-Secret"])

_PUBLIC_AUTH_PATHS = {"/api/v1/auth/register", "/api/v1/auth/login"}

def _local_device_profile_for_request(path: str) -> tuple[str, str | None] | None:
    """Map local production routes to the workload preflight they must pass."""
    video_patterns = (
        r"^/api/projects/[^/]+/movie-pipeline/source/video$",
        r"^/api/projects/[^/]+/movie-pipeline/stages/analysis/run$",
        r"^/api/v1/workspace/projects/[^/]+/video-intake$",
    )
    if any(re.fullmatch(pattern, path) for pattern in video_patterns):
        return ("movie_processing", None)

    conversion = re.fullmatch(
        r"^/api/v1/workspace/projects/([A-Za-z0-9_-]+)/assets/([A-Za-z0-9_-]+)/convert$",
        path,
    )
    if conversion:
        project_id, asset_id = conversion.groups()
        try:
            folder = manager.path_for(project_id)
            index = folder / "assets" / "assets.json"
            if index.is_file():
                rows = json.loads(index.read_text(encoding="utf-8")).get("assets", [])
                record = next((item for item in rows if item.get("asset_id") == asset_id), None)
                if record:
                    suffix = Path(record.get("path", "")).suffix.lower()
                    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
                        return ("image_to_3d", None)
                    return ("procedural_3d", project_id)
        except (OSError, ValueError, TypeError):
            pass

    project_match = re.match(
        r"^/api/(?:projects|v1/workspace/projects)/([A-Za-z0-9_-]+)(?:/|$)",
        path,
    )
    if not project_match:
        return None
    project_id = project_match.group(1)
    try:
        definition = manager.load(project_id)
        dimension = str(getattr(definition.project, "dimension", "3d")).lower()
    except Exception:
        dimension = "3d"
    project_profile = "editor_2d" if dimension == "2d" else "procedural_3d"

    if path.endswith("/jobs"):
        return (project_profile, project_id)
    if path.endswith("/generate") or path.endswith("/godot-check"):
        return (project_profile, project_id)
    if re.search(r"/movie-pipeline/(?:source/photo|player/build|environment/build)$", path):
        return ("procedural_3d", project_id)
    if re.search(
        r"/creator-workflow/(?:player/build|environment/build|actors-props/build)$",
        path,
    ):
        return ("procedural_3d", project_id)
    if re.search(r"/creator-workflow/(?:gameplay/compile|assembly/build)$", path):
        return (project_profile, project_id)
    return None


@app.middleware("http")
async def nexora_identity_and_project_scope(request: Request, call_next):
    path = request.url.path
    if request.method.upper() == "OPTIONS":
        return await call_next(request)

    # The hosted API is a control plane and finished-artifact host. All source
    # ingestion, media processing, generation, conversion and game exports are
    # rejected here unless this exact process is the creator's loopback agent.
    if not LOCAL_AGENT_MODE and is_local_compute_only_request(request.method, path):
        return JSONResponse(local_compute_block_payload(), status_code=409)

    if not path.startswith("/api/") or path in {"/api/capabilities"}:
        return await call_next(request)
    if path in _PUBLIC_AUTH_PATHS:
        return await call_next(request)

    authorization = request.headers.get("authorization", "").strip()
    supplied_token = authorization.partition(" ")[2].strip() if authorization.lower().startswith("bearer ") else ""
    if LOCAL_AGENT_MODE:
        principal = verify_local_access_token(supplied_token)
        if not principal:
            return JSONResponse({"detail": "Pair this browser with the local NEXORA agent before using the Foundry engine."}, status_code=401)
        identity = {
            "id": principal.user_id,
            "profile": {"id": principal.user_id, "display_name": "Local creator"},
        }
    else:
        identity = {"id": "local", "profile": {"id": "local"}}
        if supplied_token:
            try:
                profile = await asyncio.to_thread(verify_access_token, supplied_token)
            except NexoraIdentityUnavailable as exc:
                return JSONResponse({"detail": str(exc)}, status_code=503)
            except Exception:
                return JSONResponse({"detail": "Could not verify the NEXORA account session."}, status_code=503)
            if not profile:
                return JSONResponse({"detail": "Your NEXORA session is invalid or has expired. Sign in again."}, status_code=401)
            identity = {"id": str(profile["id"]), "profile": profile}
        elif AUTH_REQUIRED:
            return JSONResponse({"detail": "Sign in to your NEXORA account."}, status_code=401)

    request.state.nexora_user_id = identity["id"]
    request.state.nexora_user = identity["profile"]

    match = re.match(r"^/api/(?:projects|v1/workspace/projects)/([A-Za-z0-9_-]+)(?:/|$)", path)
    is_project_collection_create = path in {"/api/projects", "/api/v1/workspace/projects"} and request.method.upper() == "POST"
    if match and not is_project_collection_create and path != "/api/v1/workspace/projects/import":
        project_id = match.group(1)
        try:
            project_folder = manager.path_for(project_id)
        except ValueError:
            return JSONResponse({"detail": "Project not found."}, status_code=404)
        owner_file = project_folder / "nexora_owner.json"
        if owner_file.is_file():
            try:
                recorded = json.loads(owner_file.read_text(encoding="utf-8")).get("user_id")
            except (OSError, ValueError):
                return JSONResponse({"detail": "Project ownership record is unreadable."}, status_code=500)
            if str(recorded) != identity["id"]:
                return JSONResponse({"detail": "Project not found."}, status_code=404)
        elif AUTH_REQUIRED:
            return JSONResponse({"detail": "This legacy project has no NEXORA account owner record. Contact NEXORA support for a verified ownership migration."}, status_code=403)
        else:
            owner_file.write_text(json.dumps({"user_id": identity["id"]}, indent=2), encoding="utf-8")

    if LOCAL_AGENT_MODE and request.method.upper() in {"POST", "PUT", "PATCH"}:
        profile_request = _local_device_profile_for_request(path)
        if profile_request:
            profile_id, project_id = profile_request
            if profile_id == "editor_2d" and project_id:
                # Scene authoring does not consume the full export profile.
                # Job creation is checked here; Android export is checked in
                # its endpoint before the export worker is queued.
                if not path.endswith("/jobs"):
                    profile_id = ""
            if profile_id:
                try:
                    require_device_profile(profile_id)
                except HTTPException as exc:
                    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    return await call_next(request)

@app.get("/health")
def health():
    return {
        "status": "ok",
        "product": "Procedural Game Foundry",
        "model_free": True,
        "staged_movie_pipeline": True,
        "local_model_workers_ready": False,
        "local_compute_agent": LOCAL_AGENT_MODE,
        "execution_location": "creator_device" if LOCAL_AGENT_MODE else "artifact_hosting_only",
        "cloud_compute_enabled": False,
    }

@app.get("/api/capabilities")
def capabilities():
    if not LOCAL_AGENT_MODE:
        return {
            "project_creation": False,
            "procedural_terrain": False,
            "scene_editing": False,
            "scene_persistence": False,
            "godot_assembly": False,
            "godot_installed": False,
            "blender_installed": False,
            "execution_location": "creator_device",
            "cloud_compute_enabled": False,
            "cloud_role": "accounts_billing_and_finished_artifact_delivery",
        }
    return {
        "project_creation": True,
        "procedural_terrain": True,
        "scene_editing": True,
        "scene_persistence": True,
        "godot_assembly": True,
        "godot_installed": bool(shutil.which("godot") or shutil.which("godot4")),
        "blender_installed": bool(shutil.which("blender")),
        "execution_location": "creator_device",
        "cloud_compute_enabled": False,
        "genres": ["science-fiction", "fantasy", "modern", "survival", "adventure"],
        "dimensions": ["2d", "3d"],
        "export_targets": ["windows", "linux", "web", "android"],
    }

@app.get("/api/projects")
def list_projects(request: Request):
    owner = getattr(request.state,"nexora_user_id","local")
    result = []
    for project in manager.list():
        folder = manager.path_for(project.id)
        owner_file = folder / "nexora_owner.json"
        if owner_file.is_file():
            try:
                if json.loads(owner_file.read_text(encoding="utf-8")).get("user_id") != owner:
                    continue
            except (OSError,ValueError):
                continue
        elif AUTH_REQUIRED:
            continue
        result.append(project.model_dump(mode="json"))
    return result

@app.post("/api/projects", status_code=201)
def create_project(request: ProjectCreate, http_request: Request):
    try:
        created = manager.create(request)
        (manager.path_for(created.id) / "nexora_owner.json").write_text(json.dumps({"user_id":getattr(http_request.state,"nexora_user_id","local")},indent=2),encoding="utf-8")
        return created.model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc

@app.get("/api/projects/{pid}")
def get_project(pid: str):
    try:
        return manager.load(pid).model_dump(mode="json")
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")

@app.get("/api/projects/{pid}/world")
def get_world(pid: str):
    try:
        project = manager.load(pid)
        folder = manager.path_for(pid)
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    saved = folder / "world.json"
    if saved.is_file():
        try:
            return WorldDocument.model_validate_json(saved.read_text(encoding="utf-8")).model_dump(mode="json")
        except Exception as exc:
            raise HTTPException(500, "Saved world document is invalid") from exc
    return WorldDocument(seed=project.project.seed, world=project.world).model_dump(mode="json")

@app.put("/api/projects/{pid}/world")
def save_world(pid: str, document: WorldDocument):
    try:
        manager.load(pid)
        folder = manager.path_for(pid)
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    result = manager.save_world(pid, document, reason="autosave")
    return {**result, "objects": len(document.objects), "seed": document.seed}


@app.get("/api/projects/{pid}/versions")
def list_project_versions(pid: str):
    try:
        return {"versions": manager.list_versions(pid)}
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/projects/{pid}/versions/{revision}/restore")
def restore_project_version(pid: str, revision: int):
    try:
        return manager.restore_version(pid, revision)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

@app.post("/api/projects/{pid}/generate", status_code=202)
def generate(pid: str, background: BackgroundTasks):
    try:
        definition = manager.load(pid)
        folder = manager.path_for(pid)
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    job = jobs.add(Job.create(pid))
    background.add_task(run_generation, job.id, definition, folder)
    return job.as_dict()

def run_generation(jid, definition, folder):
    try:
        jobs.update(jid, state=JobState.RUNNING, progress=10, message="Generating deterministic terrain")
        world_path = folder / "world.json"
        world_state = WorldDocument.model_validate_json(world_path.read_text(encoding="utf-8")).model_dump(mode="json") if world_path.is_file() else None
        assemble_godot_project(definition, folder / "game", world_state)
        jobs.update(jid, state=JobState.VALIDATING, progress=80, message="Validating generated project")
        report = validate_project(folder)
        if not report["valid"]:
            raise RuntimeError("; ".join(report["errors"]))
        jobs.update(jid, state=JobState.COMPLETED, progress=100, message="Godot project generated", error=None)
    except Exception as exc:
        jobs.update(jid, state=JobState.FAILED, message="Generation failed", error=str(exc))

@app.get("/api/jobs/{jid}")
def get_job(jid: str):
    job = jobs.get(jid)
    if not job:
        raise HTTPException(404, "Job not found")
    return job.as_dict()

@app.get("/api/projects/{pid}/validate")
def validate(pid: str):
    try:
        path = manager.path_for(pid)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not path.is_dir():
        raise HTTPException(404, "Project not found")
    return validate_project(path)

@app.post("/api/projects/{pid}/godot-check")
def godot_check(pid: str):
    try:
        path = manager.path_for(pid) / "game"
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not path.is_dir():
        raise HTTPException(409, "Generate the game first")
    return headless_check(path)

@app.get("/api/projects/{pid}/files")
def project_files(pid: str):
    try:
        root = manager.path_for(pid)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not root.is_dir():
        raise HTTPException(404, "Project not found")
    return {"files": [str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()]}


# Movie-to-game pipeline: persisted, creator-approved stage state machine.
from core.movie_pipeline.models import PipelineCreate, StageDecision, StageId, StageState, new_pipeline
from core.movie_pipeline.service import PipelineError, PipelineStore
from core.movie_pipeline.worker import analyze_project

@app.post("/api/projects/{pid}/movie-pipeline", status_code=201)
def create_movie_pipeline(pid: str, request: PipelineCreate):
    try:
        folder = manager.path_for(pid)
        manager.load(pid)
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    rights = request.rights
    if not (rights.has_photo_rights and rights.likeness_consent and rights.accepts_original_assets_only):
        raise HTTPException(400, "Confirm photo rights, likeness consent and original-asset generation before processing")
    store = PipelineStore(folder)
    if store.path.exists():
        raise HTTPException(409, "A movie pipeline already exists for this project")
    return store.save(new_pipeline(pid, rights)).model_dump(mode="json")

@app.get("/api/projects/{pid}/movie-pipeline")
def get_movie_pipeline(pid: str):
    try:
        folder = manager.path_for(pid)
        manager.load(pid)
        return PipelineStore(folder).load().model_dump(mode="json")
    except FileNotFoundError as exc:
        raise HTTPException(404, "Project or movie pipeline not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

@app.post("/api/projects/{pid}/movie-pipeline/stages/{stage_id}/approve")
def approve_movie_stage(pid: str, stage_id: StageId, request: StageDecision):
    try:
        folder = manager.path_for(pid)
        manager.load(pid)
        result = PipelineStore(folder).approve(stage_id, request.note)
        return result.model_dump(mode="json")
    except FileNotFoundError as exc:
        raise HTTPException(404, "Project or movie pipeline not found") from exc
    except PipelineError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

@app.post("/api/projects/{pid}/movie-pipeline/stages/{stage_id}/regenerate")
def regenerate_movie_stage(pid: str, stage_id: StageId):
    try:
        folder = manager.path_for(pid)
        manager.load(pid)
        result = PipelineStore(folder).regenerate(stage_id)
        return result.model_dump(mode="json")
    except FileNotFoundError as exc:
        raise HTTPException(404, "Project or movie pipeline not found") from exc
    except PipelineError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


from core.movie_pipeline.ingestion import UploadRejected, store_upload

async def _attach_movie_input(pid: str, kind: str, upload: UploadFile):
    try:
        folder = manager.path_for(pid)
        manager.load(pid)
        store = PipelineStore(folder)
        document = store.load()
    except FileNotFoundError as exc:
        raise HTTPException(404, "Project or movie pipeline not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    attribute = "source_photo" if kind == "photo" else "source_video"
    if getattr(document, attribute):
        raise HTTPException(409, f"A {kind} input is already attached; remove it before replacing")
    try:
        metadata = await store_upload(upload, kind, store.folder / "uploads")
    except UploadRejected as exc:
        raise HTTPException(400, str(exc)) from exc
    setattr(document, attribute, metadata)
    store.save(document)
    return {"attached": True, "kind": kind, "metadata": metadata}

@app.post("/api/projects/{pid}/movie-pipeline/source/photo", status_code=201)
async def upload_player_portrait(pid: str, file: UploadFile = File(...)):
    return await _attach_movie_input(pid, "photo", file)

@app.post("/api/projects/{pid}/movie-pipeline/source/video", status_code=201)
async def upload_source_movie(pid: str, file: UploadFile = File(...)):
    return await _attach_movie_input(pid, "video", file)


@app.post("/api/projects/{pid}/movie-pipeline/stages/analysis/run", status_code=202)
def run_movie_analysis(pid: str, background: BackgroundTasks):
    """Queue local FFmpeg analysis; poll the returned PGF job id for completion."""
    try:
        folder = manager.path_for(pid)
        manager.load(pid)
        pipeline = PipelineStore(folder).load()
    except FileNotFoundError as exc:
        raise HTTPException(404, "Project or movie pipeline not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    analysis = next(item for item in pipeline.stages if item.stage == StageId.ANALYSIS)
    if analysis.state.value != "READY":
        raise HTTPException(409, "Analysis stage must be READY before it can run")
    if not pipeline.source_video:
        raise HTTPException(409, "Upload the movie video before starting analysis")
    job = jobs.add(Job.create(pid))
    background.add_task(run_movie_analysis_job, job.id, folder)
    return job.as_dict()

def run_movie_analysis_job(job_id: str, folder: Path):
    try:
        jobs.update(job_id, state=JobState.RUNNING, progress=5, message="Starting local media analysis")
        result = analyze_project(folder)
        jobs.update(job_id, state=JobState.COMPLETED, progress=100,
                    message=f"Analysis ready for review ({len(result.get('keyframes', []))} keyframes)", error=None)
    except Exception as exc:
        jobs.update(job_id, state=JobState.FAILED, message="Movie analysis failed", error=str(exc))


# Creator-authored story and deterministic procedural 3D world tools.
from core.movie_pipeline.story import StoryBrief
from core.movie_pipeline.procedural_world import build_world_spec

@app.put("/api/projects/{pid}/movie-pipeline/story")
def save_creator_story(pid: str, brief: StoryBrief):
    """Save a creator-written story/instruction set; no model or inference service is called."""
    try:
        folder = manager.path_for(pid)
        manager.load(pid)
        pipeline = PipelineStore(folder).load()
    except FileNotFoundError as exc:
        raise HTTPException(404, "Project or movie pipeline not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if brief.mode in ("movie", "guided") and not pipeline.source_video:
        raise HTTPException(409, "Upload a movie clip for movie or guided mode")
    if brief.mode in ("movie", "guided") and not pipeline.rights.has_video_rights:
        raise HTTPException(409, "Confirm that you own or have permission to use the movie clip before selecting movie or guided mode")
    if not pipeline.source_photo:
        raise HTTPException(409, "Upload the player's portrait before creating the player avatar")
    story = brief.as_manifest()
    path = PipelineStore(folder).folder / "story.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(story, indent=2), encoding="utf-8")
    temporary.replace(path)
    # A story-first project has no film-analysis prerequisite; explicitly skip that stage.
    if brief.mode == "story":
        records = {record.stage: record for record in pipeline.stages}
        records[StageId.ANALYSIS].state = StageState.APPROVED
        records[StageId.ANALYSIS].summary = "Skipped by creator: story-first workflow"
        records[StageId.PLAYER].state = __import__("core.movie_pipeline.models", fromlist=["StageState"]).StageState.READY
        records[StageId.PLAYER].summary = "Portrait and creator story ready for procedural player generation"
        pipeline.active_stage = StageId.PLAYER
        PipelineStore(folder).save(pipeline)
    return {"saved": True, "story": story}

@app.get("/api/projects/{pid}/movie-pipeline/story")
def get_creator_story(pid: str):
    try:
        folder = manager.path_for(pid)
        manager.load(pid)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Project not found") from exc
    path = PipelineStore(folder).folder / "story.json"
    if not path.is_file():
        raise HTTPException(404, "No creator story has been saved")
    return json.loads(path.read_text(encoding="utf-8"))

@app.post("/api/projects/{pid}/movie-pipeline/environment/build")
def build_procedural_environment(pid: str):
    """Create a deterministic 3D scene specification for Blender; no AI models involved."""
    try:
        folder = manager.path_for(pid)
        manager.load(pid)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Project not found") from exc
    store = PipelineStore(folder)
    try:
        pipeline = store.load()
    except FileNotFoundError as exc:
        raise HTTPException(404, "Movie pipeline not found") from exc
    stage = next(item for item in pipeline.stages if item.stage == StageId.ENVIRONMENT)
    if stage.state != StageState.READY:
        raise HTTPException(409, "Approve the procedural player stage before generating the environment")
    story_path = store.folder / "story.json"
    if not story_path.is_file():
        raise HTTPException(409, "Save the creator story before generating the 3D environment")
    story = json.loads(story_path.read_text(encoding="utf-8"))
    spec = build_world_spec(story)
    output = PipelineStore(folder).folder / "environment" / "world-spec.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    temporary.replace(output)
    blender = shutil.which("blender")
    if not blender:
        raise HTTPException(503, "Blender is required to turn the saved 3D geometry specification into a GLB scene")
    script = Path(__file__).resolve().parents[2] / "blender" / "scripts" / "build_movie_world.py"
    glb = output.parent / "environment.glb"
    stage.state = StageState.RUNNING
    stage.summary = "Building procedural 3D environment with Blender"
    store.save(pipeline)
    try:
        result = subprocess.run([blender, "--background", "--python", str(script), "--",
                                 "--spec", str(output), "--output", str(glb)],
                                capture_output=True, text=True, timeout=900, check=True)
    except subprocess.TimeoutExpired as exc:
        stage.state = StageState.FAILED; stage.error = "Blender environment generation exceeded 15 minutes"; store.save(pipeline)
        raise HTTPException(504, stage.error) from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "Blender failed")[-2500:]
        stage.state = StageState.FAILED; stage.error = detail; stage.summary = "3D environment generation failed"; store.save(pipeline)
        raise HTTPException(500, "3D environment generation failed: " + detail) from exc
    if not glb.is_file() or glb.stat().st_size < 1024:
        stage.state = StageState.FAILED; stage.error = "Blender did not produce a valid GLB scene"; store.save(pipeline)
        raise HTTPException(500, stage.error)
    reviewed = store.mark_review(StageId.ENVIRONMENT, {"glb_scene":str(glb.relative_to(folder)), "geometry_spec":str(output.relative_to(folder)), "landmarks":len(spec["landmarks"]), "props":len(spec["props"]), "dimensions":spec["dimensions"], "glb_bytes":glb.stat().st_size, "requires_creator_review":True}, "Procedural 3D environment generated; inspect geometry and navigation before approval")
    return {"generated": True, "stage":next(item.model_dump(mode="json") for item in reviewed.stages if item.stage==StageId.ENVIRONMENT), "geometry_spec": str(output.relative_to(folder)),
            "glb_scene": str(glb.relative_to(folder)), "glb_bytes": glb.stat().st_size,
            "landmarks": len(spec["landmarks"]), "props": len(spec["props"]),
            "dimensions": spec["dimensions"], "requires_creator_review": True}


@app.post("/api/projects/{pid}/movie-pipeline/player/build")
def build_procedural_player(pid: str, request: dict):
    """Build a portrait-referenced, editable procedural humanoid using Blender only."""
    try:
        folder = manager.path_for(pid)
        manager.load(pid)
        store = PipelineStore(folder)
        pipeline = store.load()
    except FileNotFoundError as exc:
        raise HTTPException(404, "Project or movie pipeline not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not pipeline.source_photo:
        raise HTTPException(409, "Upload a full-body player portrait first")
    story_path = store.folder / "story.json"
    if not story_path.is_file():
        raise HTTPException(409, "Save the creator story before generating the player")
    stage = next(item for item in pipeline.stages if item.stage == StageId.PLAYER)
    if stage.state.value != "READY":
        raise HTTPException(409, "Approve movie analysis first, or save a story-first brief, before generating the player")
    blender = shutil.which("blender")
    if not blender:
        raise HTTPException(503, "Blender is required for procedural character generation")
    proportions = request.get("proportions", {})
    if not isinstance(proportions, dict):
        raise HTTPException(400, "Proportions must be an object")
    allowed = {"height", "shoulder_width", "hip_width", "leg_ratio", "build", "face_center_x", "face_top", "face_width", "face_height"}
    if set(proportions) - allowed:
        raise HTTPException(400, "Unknown avatar proportion field")
    defaults = {"height":1.78,"shoulder_width":0.46,"hip_width":0.34,"leg_ratio":0.52,"build":1.0,"face_center_x":0.5,"face_top":0.035,"face_width":0.22,"face_height":0.16}
    values = {**defaults, **proportions}
    bounds = {"height":(1.35,2.2),"shoulder_width":(.32,.7),"hip_width":(.24,.55),"leg_ratio":(.42,.62),"build":(.75,1.3),"face_center_x":(.1,.9),"face_top":(0,.6),"face_width":(.12,.4),"face_height":(.08,.3)}
    for key,(low,high) in bounds.items():
        try: values[key] = float(values[key])
        except (TypeError,ValueError) as exc: raise HTTPException(400,f"{key} must be numeric") from exc
        if not low <= values[key] <= high: raise HTTPException(400,f"{key} must be between {low} and {high}")
    if values["face_top"] + values["face_height"] > 1 or values["face_center_x"] - values["face_width"]/2 < 0 or values["face_center_x"] + values["face_width"]/2 > 1:
        raise HTTPException(400, "Face crop rectangle must stay inside the uploaded portrait")
    portrait = (store.folder / pipeline.source_photo["storage_key"]).resolve()
    uploads = (store.folder / "uploads").resolve()
    if uploads not in portrait.parents or not portrait.is_file():
        raise HTTPException(400, "Player portrait is missing or outside the upload directory")
    avatar_dir = store.folder / "player" / f"revision-{stage.revision}"
    avatar_dir.mkdir(parents=True,exist_ok=True)
    spec_path = avatar_dir / "avatar.json"
    spec_path.write_text(json.dumps({"proportions":values,"face_crop":{"center_x":values["face_center_x"],"top":values["face_top"],"width":values["face_width"],"height":values["face_height"]},"portrait_sha256":pipeline.source_photo.get("sha256"),
                                    "identity_source":"uploaded_portrait","creator_review_required":True},indent=2),encoding="utf-8")
    glb = avatar_dir / "player-avatar.glb"
    script = Path(__file__).resolve().parents[2] / "blender" / "scripts" / "build_player_avatar.py"
    stage.state = StageState.RUNNING
    stage.summary = "Building procedural humanoid mesh and armature with Blender"
    store.save(pipeline)
    try:
        result = subprocess.run([blender,"--background","--python",str(script),"--","--portrait",str(portrait),
                                 "--output",str(glb),"--spec",str(spec_path)],
                                capture_output=True,text=True,timeout=900,check=True)
    except (subprocess.TimeoutExpired,subprocess.CalledProcessError) as exc:
        stage.state = StageState.FAILED
        stage.error = (getattr(exc,"stderr",None) or str(exc))[-2500:]
        stage.summary = "Procedural player generation failed"
        store.save(pipeline)
        raise HTTPException(500,stage.error) from exc
    if not glb.is_file() or glb.stat().st_size < 1024:
        stage.state = StageState.FAILED
        stage.error = "Blender did not produce a valid GLB avatar"
        store.save(pipeline)
        raise HTTPException(500,stage.error)
    rig_summary = {}
    for line in reversed((result.stdout or "").splitlines()):
        try:
            rig_summary = json.loads(line)
            break
        except json.JSONDecodeError:
            continue
    updated = store.mark_review(StageId.PLAYER,{"glb_scene":str(glb.relative_to(folder)),
        "spec":str(spec_path.relative_to(folder)),"glb_bytes":glb.stat().st_size,
        "portrait_sha256":pipeline.source_photo.get("sha256"),"generator":"PGF procedural humanoid v1",
        "proportions":values,"bone_count":rig_summary.get("bone_count"),"requires_creator_review":True},
        "Procedural player avatar generated; inspect proportions, face and rig before approval")
    return {"generated":True,"stage":next(item.model_dump(mode="json") for item in updated.stages if item.stage==StageId.PLAYER),
            "glb_scene":str(glb.relative_to(folder)),"glb_bytes":glb.stat().st_size,
            "proportions":values,"requires_creator_review":True}


@app.get("/api/projects/{pid}/movie-pipeline/assets/{asset_path:path}")
def get_movie_pipeline_asset(pid: str, asset_path: str):
    """Serve generated, project-scoped movie-pipeline artifacts for creator preview/download."""
    try:
        folder = manager.path_for(pid)
        manager.load(pid)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Project not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    relative = Path(asset_path)
    allowed_media={".glb":("model/gltf-binary","model"),".wav":("audio/wav","audio"),".json":("application/json","data"),".gd":("text/plain; charset=utf-8","script")}
    suffix=relative.suffix.lower()
    if relative.is_absolute() or ".." in relative.parts or suffix not in allowed_media:
        raise HTTPException(400, "Only project-scoped generated GLB, WAV, JSON and GDScript assets can be retrieved")
    if not relative.parts or relative.parts[0] != "movie_pipeline" or len(relative.parts) < 3:
        raise HTTPException(400, "Asset path is outside generated movie-pipeline artifacts")
    target = (folder / relative).resolve()
    root = (folder / "movie_pipeline").resolve()
    if root not in target.parents or not target.is_file():
        raise HTTPException(404, "Generated asset not found")
    return FileResponse(target, media_type=allowed_media[suffix][0], filename=target.name)


# Creator-authored deterministic actor and prop generation routes.
from core.movie_pipeline.actors_api import register_actor_props_routes
register_actor_props_routes(app, lambda: manager)


# Deterministic, creator-authored procedural audio generation routes.
from core.movie_pipeline.audio_api import register_audio_routes
register_audio_routes(app, lambda: manager)


# Deterministic, creator-authored Gameplay Compiler routes.
from core.movie_pipeline.gameplay_api import register_gameplay_routes
register_gameplay_routes(app, lambda: manager)


# Approval-gated Godot assembly for the movie-to-game pipeline.
from core.movie_pipeline.assembly import register_assembly_routes
register_assembly_routes(app, lambda: manager)

# Project-scoped Blender/creator asset ingestion with structural glTF validation.
from core.asset_registry.api import register_asset_routes
register_asset_routes(app, lambda: manager)


# NEXORA Studio Pro integrated workspace adapter. It reuses the Foundry project
# manager, asset registry, Godot assembler and job service rather than creating
# a second project database.
from core.nexora_workspace.api import register_nexora_workspace_routes
register_nexora_workspace_routes(app, manager, jobs)

# Local-only manifests, toolchain lockfiles, backup/import and release preparation.
from core.nexora_workspace.local_factory import register_local_factory_routes
register_local_factory_routes(app, manager)

# Desktop IDE, file explorer, local snapshots, toolchain setup and publisher readiness.
from core.nexora_workspace.desktop_api import register_desktop_factory_routes
register_desktop_factory_routes(app, manager)


# Episode-driven Creator Flow, asset conversion workers and Pochi plan reconciliation.
from core.nexora_workspace.creator_workflow import register_creator_workflow_routes
register_creator_workflow_routes(app, manager, jobs)

# NEXORA has its own registration, login and revocable account sessions.
register_nexora_auth_routes(app)

# Desktop project, toolchain, Drive and release routes are registered once
# above by core.nexora_workspace.desktop_api.
