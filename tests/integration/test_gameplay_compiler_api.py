import json
from fastapi.testclient import TestClient
from services.api.main import app, manager
from core.movie_pipeline.models import StageId, StageState
from core.movie_pipeline.service import PipelineStore

client = TestClient(app)

def _project(tmp_path, monkeypatch):
    from core.project_engine.manager import ProjectManager
    local_manager = ProjectManager(tmp_path / "projects")
    monkeypatch.setattr("services.api.main.manager", local_manager)
    project = client.post("/api/projects", json={"name":"Gameplay Compiler Test","seed":12}).json()
    pid = project["id"]
    client.post(f"/api/projects/{pid}/movie-pipeline", json={"rights":{
        "has_video_rights":False,"has_photo_rights":True,"likeness_consent":True,"accepts_original_assets_only":True
    }})
    folder = local_manager.path_for(pid)
    store = PipelineStore(folder)
    pipeline = store.load()
    for record in pipeline.stages:
        record.state = StageState.APPROVED if record.stage in (StageId.ANALYSIS,StageId.PLAYER,StageId.ENVIRONMENT,StageId.ACTORS_PROPS,StageId.AUDIO) else StageState.READY if record.stage == StageId.GAMEPLAY else StageState.LOCKED
    store.save(pipeline)
    root = store.folder
    (root / "story.json").write_text(json.dumps({"title":"Creator story"}))
    actors = root / "actors-props" / "revision-0"
    actors.mkdir(parents=True)
    (actors / "actors-props.manifest.json").write_text(json.dumps({"actors":[{"id":"guard-1"}],"props":[{"id":"key-1"}]}))
    audio = root / "audio" / "revision-0"
    audio.mkdir(parents=True)
    (audio / "audio-manifest.json").write_text(json.dumps({"effects":[{"id":"jump-sfx"}]}))
    return pid, root

def _spec():
    return {"player":{"move_speed":5,"jump_velocity":4.5,"gravity":9.8,"health":100,"inventory_capacity":12},
      "missions":[{"id":"mission-1","title":"Escape","description":"Find the exit","objectives":[
        {"id":"find-key","title":"Find key","description":"Collect the key","kind":"collect","target_id":"key-1","required_count":1}]}],
      "actor_behaviours":[{"actor_id":"guard-1","behaviour":"patrol"}],
      "interactions":[{"prop_id":"key-1","action":"collect","objective_id":"find-key","item_id":"brass-key"}],
      "audio_bindings":[{"event":"player_jump","cue_id":"jump-sfx"}],
      "win_condition":"all_objectives_complete","lose_condition":"health_depleted"}

def test_compiles_runtime_and_enters_review(tmp_path, monkeypatch):
    pid, root = _project(tmp_path, monkeypatch)
    response = client.post(f"/api/projects/{pid}/movie-pipeline/gameplay/compile", json=_spec())
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["compiled"] is True and data["mission_count"] == 1 and data["objective_count"] == 1
    assert data["audio_binding_count"] == 1 and data["requires_creator_review"] is True
    output = root / "gameplay" / "revision-0"
    assert (output / "gameplay.json").is_file()
    assert "jump-sfx" in (output / "audio-events.json").read_text()
    assert (output / "runtime" / "GameplayDirector.gd").is_file()
    assert PipelineStore(root.parent).load().stages[5].state == StageState.REVIEW

def test_rejects_missing_upstream_approval(tmp_path, monkeypatch):
    pid, root = _project(tmp_path, monkeypatch)
    store = PipelineStore(root.parent)
    pipeline = store.load()
    next(item for item in pipeline.stages if item.stage == StageId.AUDIO).state = StageState.REVIEW
    store.save(pipeline)
    response = client.post(f"/api/projects/{pid}/movie-pipeline/gameplay/compile", json=_spec())
    assert response.status_code == 409

def test_rejects_unknown_actor_prop_and_audio_refs(tmp_path, monkeypatch):
    pid, root = _project(tmp_path, monkeypatch)
    spec = _spec(); spec["actor_behaviours"][0]["actor_id"] = "missing"
    assert client.post(f"/api/projects/{pid}/movie-pipeline/gameplay/compile", json=spec).status_code == 422
    spec = _spec(); spec["interactions"][0]["prop_id"] = "missing"
    assert client.post(f"/api/projects/{pid}/movie-pipeline/gameplay/compile", json=spec).status_code == 422
    spec = _spec(); spec["audio_bindings"][0]["cue_id"] = "missing"
    assert client.post(f"/api/projects/{pid}/movie-pipeline/gameplay/compile", json=spec).status_code == 422

def test_rejects_duplicate_objective_ids(tmp_path, monkeypatch):
    pid, root = _project(tmp_path, monkeypatch)
    spec = _spec()
    spec["missions"].append({"id":"mission-2","title":"Second","description":"More","objectives":[
      {"id":"find-key","title":"Duplicate","description":"Duplicate","kind":"reach"}]})
    assert client.post(f"/api/projects/{pid}/movie-pipeline/gameplay/compile", json=spec).status_code == 422
