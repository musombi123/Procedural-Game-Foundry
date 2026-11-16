import os,shutil
from pathlib import Path
from fastapi import FastAPI,HTTPException,BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from core.project_engine.models import ProjectCreate
from core.project_engine.manager import ProjectManager
from core.orchestration.jobs import Job,JobRegistry,JobState
from core.game_assembler.godot import assemble_godot_project
from core.validation.validator import validate_project
from core.build_engine.godot_cli import headless_check
DATA=Path(os.environ.get("PGF_DATA_DIR",".pgf-data")).resolve(); manager=ProjectManager(DATA/"projects"); jobs=JobRegistry()
app=FastAPI(title="Procedural Game Foundry API",version="0.1.0",description="Model-free local-first game creation service")
app.add_middleware(CORSMiddleware,allow_origins=["http://localhost:5173","http://127.0.0.1:5173","tauri://localhost"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
@app.get("/health")
def health(): return {"status":"ok","product":"Procedural Game Foundry","model_free":True}
@app.get("/api/capabilities")
def capabilities(): return {"project_creation":True,"procedural_terrain":True,"godot_assembly":True,"godot_installed":bool(shutil.which("godot") or shutil.which("godot4")),"blender_installed":bool(shutil.which("blender")),"genres":["science-fiction","fantasy","modern","survival","adventure"],"dimensions":["2d","3d"],"export_targets":["windows","linux","web","android"]}
@app.get("/api/projects")
def list_projects(): return [p.model_dump(mode="json") for p in manager.list()]
@app.post("/api/projects",status_code=201)
def create_project(request: ProjectCreate):
    try: return manager.create(request).model_dump(mode="json")
    except Exception as exc: raise HTTPException(400,str(exc)) from exc
@app.get("/api/projects/{pid}")
def get_project(pid: str):
    try: return manager.load(pid).model_dump(mode="json")
    except FileNotFoundError: raise HTTPException(404,"Project not found")
@app.post("/api/projects/{pid}/generate",status_code=202)
def generate(pid: str,background: BackgroundTasks):
    try: definition=manager.load(pid); folder=manager.path_for(pid)
    except FileNotFoundError: raise HTTPException(404,"Project not found")
    job=jobs.add(Job.create(pid)); background.add_task(run_generation,job.id,definition,folder); return job.as_dict()
def run_generation(jid,definition,folder):
    try:
        jobs.update(jid,state=JobState.RUNNING,progress=10,message="Generating deterministic terrain")
        assemble_godot_project(definition,folder/"game")
        jobs.update(jid,state=JobState.VALIDATING,progress=80,message="Validating generated project")
        report=validate_project(folder)
        if not report["valid"]: raise RuntimeError("; ".join(report["errors"]))
        jobs.update(jid,state=JobState.COMPLETED,progress=100,message="Godot project generated",error=None)
    except Exception as exc: jobs.update(jid,state=JobState.FAILED,message="Generation failed",error=str(exc))
@app.get("/api/jobs/{jid}")
def get_job(jid: str):
    job=jobs.get(jid)
    if not job: raise HTTPException(404,"Job not found")
    return job.as_dict()
@app.get("/api/projects/{pid}/validate")
def validate(pid: str):
    try: path=manager.path_for(pid)
    except ValueError as exc: raise HTTPException(400,str(exc))
    if not path.is_dir(): raise HTTPException(404,"Project not found")
    return validate_project(path)
@app.post("/api/projects/{pid}/godot-check")
def godot_check(pid: str):
    try: path=manager.path_for(pid)/"game"
    except ValueError as exc: raise HTTPException(400,str(exc))
    if not path.is_dir(): raise HTTPException(409,"Generate the game first")
    return headless_check(path)
@app.get("/api/projects/{pid}/files")
def project_files(pid: str):
    try: root=manager.path_for(pid)
    except ValueError as exc: raise HTTPException(400,str(exc))
    if not root.is_dir(): raise HTTPException(404,"Project not found")
    return {"files":[str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()]}
