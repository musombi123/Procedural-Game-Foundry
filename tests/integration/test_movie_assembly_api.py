import json
import wave
from pathlib import Path
from subprocess import CompletedProcess
from fastapi.testclient import TestClient

from services.api.main import app
from core.movie_pipeline.models import StageId, StageState
from core.movie_pipeline.service import PipelineStore
from core.gameplay_compiler.compiler import compile_gameplay

client = TestClient(app)

def _fixture(tmp_path, monkeypatch, *, gameplay_approved=True):
    from core.project_engine.manager import ProjectManager
    import core.movie_pipeline.assembly as assembly
    local_manager = ProjectManager(tmp_path / "projects")
    monkeypatch.setattr("services.api.main.manager", local_manager)
    monkeypatch.setattr(assembly.shutil, "which", lambda _name: "/usr/bin/godot")
    monkeypatch.setattr(assembly.subprocess, "run", lambda *args, **kwargs: CompletedProcess(args[0], 0, "PGF_ASSEMBLY_SMOKE_OK", ""))
    project = client.post("/api/projects", json={"name":"Assembly Integration Test","seed":91}).json()
    pid = project["id"]
    client.post(f"/api/projects/{pid}/movie-pipeline", json={"rights":{
        "has_video_rights":False,"has_photo_rights":True,"likeness_consent":True,"accepts_original_assets_only":True
    }})
    folder = local_manager.path_for(pid)
    store = PipelineStore(folder)
    pipeline = store.load()
    for record in pipeline.stages:
        if record.stage in (StageId.ANALYSIS, StageId.PLAYER, StageId.ENVIRONMENT, StageId.ACTORS_PROPS, StageId.AUDIO):
            record.state = StageState.APPROVED
        elif record.stage == StageId.GAMEPLAY:
            record.state = StageState.APPROVED if gameplay_approved else StageState.REVIEW
        elif record.stage == StageId.ASSEMBLY:
            record.state = StageState.READY
    store.save(pipeline)
    root = store.folder
    def write(rel, content=b"fixture-glb"):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path
    write("player/revision-0/player-avatar.glb")
    write("environment/environment.glb")
    write("environment/world-spec.json", json.dumps({"dimensions":[48,48,48],"terrain":{"segments":8,"amplitude":1,"frequency":0.03},"landmarks":[],"props":[]}).encode())
    write("actors-props/revision-0/actors-props.glb")
    actors_manifest = {"actors":[{"id":"guard-1","rig":"guard-1_rig"}],"props":[{"id":"key-1"}]}
    write("actors-props/revision-0/actors-props.manifest.json", json.dumps(actors_manifest).encode())
    actors_spec = {"actors":[{"id":"guard-1","position":[2,0,0],"scale":1}],"props":[{"id":"key-1","position":[1,0,0],"scale":1}]}
    write("actors-props/revision-0/actors-props.json", json.dumps(actors_spec).encode())
    audio_dir = root / "audio/revision-0"
    audio_dir.mkdir(parents=True)
    with wave.open(str(audio_dir / "pickup.wav"), "wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(22050); wav.writeframes(b"\x00\x00" * 128)
    audio_manifest = {"effects":[{"id":"pickup-sfx","file":"pickup.wav"}],"music":None}
    write("audio/revision-0/audio-manifest.json", json.dumps(audio_manifest).encode())
    spec = {"player":{"move_speed":5,"jump_velocity":4.5,"gravity":9.8,"health":100,"inventory_capacity":10},
      "missions":[{"id":"mission-1","title":"Find the key","description":"Collect the key","objectives":[
        {"id":"collect-key","title":"Collect key","description":"Pick up the key","kind":"collect","target_id":"key-1","required_count":1}]}],
      "actor_behaviours":[{"actor_id":"guard-1","behaviour":"patrol","move_speed":2.5,"detection_range":10,"attack_range":1.8,"damage":10}],
      "interactions":[{"prop_id":"key-1","action":"collect","objective_id":"collect-key","item_id":"key"}],
      "audio_bindings":[{"event":"objective_complete","cue_id":"pickup-sfx"}],
      "win_condition":"all_objectives_complete","lose_condition":"health_depleted"}
    gameplay_dir = root / "gameplay/revision-0"
    compile_gameplay(gameplay_dir, spec, audio_manifest)
    return pid, folder, root

def test_assembly_requires_gameplay_approval(tmp_path, monkeypatch):
    pid, _folder, _root = _fixture(tmp_path, monkeypatch, gameplay_approved=False)
    response = client.post(f"/api/projects/{pid}/movie-pipeline/assembly/build")
    assert response.status_code == 409
    assert "Approve" in response.json()["detail"]

def test_assembly_copies_assets_wires_runtime_and_enters_review(tmp_path, monkeypatch):
    pid, folder, root = _fixture(tmp_path, monkeypatch)
    response = client.post(f"/api/projects/{pid}/movie-pipeline/assembly/build")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["assembled"] is True
    assert data["validation"]["editor_import"] == "passed"
    assert data["validation"]["gameplay_e2e"] == "passed"
    assert data["mission_count"] == 1 and data["objective_count"] == 1
    game = folder / "game"
    for path in ["project.godot","main.tscn","assets/player-avatar.glb","assets/environment.glb",
                 "assets/actors-props.glb","assets/audio/pickup.wav","scripts/ActorHitbox.gd",
                 "scripts/InteractableProp.gd","scripts/main.gd","gameplay/gameplay.json"]:
        assert (game / path).is_file(), path
    pipeline = PipelineStore(folder).load()
    assert next(item for item in pipeline.stages if item.stage == StageId.ASSEMBLY).state == StageState.REVIEW
    download = client.get(f"/api/projects/{pid}/movie-pipeline/assembly/download")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/zip")

def test_assembly_rejects_manifest_path_traversal(tmp_path, monkeypatch):
    pid, folder, root = _fixture(tmp_path, monkeypatch)
    manifest = root / "audio/revision-0/audio-manifest.json"
    manifest.write_text(json.dumps({"effects":[{"id":"bad","file":"../../outside.wav"}],"music":None}))
    response = client.post(f"/api/projects/{pid}/movie-pipeline/assembly/build")
    assert response.status_code == 500
    assert "assembly failed" in response.json()["detail"].lower()
