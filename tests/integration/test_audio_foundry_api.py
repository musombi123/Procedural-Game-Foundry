from pathlib import Path
from fastapi.testclient import TestClient
import services.api.main as api
from core.movie_pipeline.models import RightsDeclaration, StageId, StageState
from core.movie_pipeline.service import PipelineStore
from core.audio_foundry.synth import render_effect, render_music, write_wav

RIGHTS=RightsDeclaration(has_video_rights=False,has_photo_rights=True,likeness_consent=True,accepts_original_assets_only=True)

def ready_audio(tmp_path,monkeypatch):
    monkeypatch.setattr(api,"manager",api.ProjectManager(tmp_path))
    client=TestClient(api.app)
    project=client.post("/api/projects",json={"name":"Audio Test"}).json(); pid=project["id"]
    client.post(f"/api/projects/{pid}/movie-pipeline",json={"rights":RIGHTS.model_dump(mode="json")})
    folder=api.manager.path_for(pid); store=PipelineStore(folder); doc=store.load()
    records={item.stage:item for item in doc.stages}
    records[StageId.PLAYER].state=StageState.APPROVED
    records[StageId.ENVIRONMENT].state=StageState.APPROVED
    records[StageId.ACTORS_PROPS].state=StageState.APPROVED
    records[StageId.AUDIO].state=StageState.READY
    store.save(doc)
    return client,pid,store

def test_audio_generation_is_deterministic_and_wav_valid(tmp_path):
    first=render_effect("impact",180,.4,17)
    second=render_effect("impact",180,.4,17)
    assert first==second
    music_a=render_music(4,9,"adventure"); music_b=render_music(4,9,"adventure")
    assert music_a==music_b
    path=tmp_path/"effect.wav"; size=write_wav(path,first)
    assert size>44 and path.read_bytes()[:4]==b"RIFF" and path.read_bytes()[8:12]==b"WAVE"

def test_audio_build_requires_actors_props_approval(tmp_path,monkeypatch):
    monkeypatch.setattr(api,"manager",api.ProjectManager(tmp_path))
    client=TestClient(api.app); project=client.post("/api/projects",json={"name":"Audio Gate"}).json(); pid=project["id"]
    client.post(f"/api/projects/{pid}/movie-pipeline",json={"rights":RIGHTS.model_dump(mode="json")})
    response=client.post(f"/api/projects/{pid}/movie-pipeline/audio/build",json={"cues":[{"id":"hit","label":"Hit"}]})
    assert response.status_code==409

def test_audio_build_review_and_wav_download(tmp_path,monkeypatch):
    client,pid,store=ready_audio(tmp_path,monkeypatch)
    response=client.post(f"/api/projects/{pid}/movie-pipeline/audio/build",json={
        "cues":[{"id":"player-hit","label":"Player hit","kind":"impact","frequency":180,"duration":.35,"seed":4,"trigger":"player damaged"}],
        "music":{"mood":"calm","duration":4,"seed":2,"loop":True}})
    assert response.status_code==200,response.text
    payload=response.json()
    assert payload["stage"]["state"]=="REVIEW"
    assert payload["effects_count"]==1 and payload["music_generated"] is True
    effect=payload["stage"]["output"]["effects"][0]["asset"]
    downloaded=client.get(f"/api/projects/{pid}/movie-pipeline/assets/{effect}")
    assert downloaded.status_code==200
    assert downloaded.headers["content-type"].startswith("audio/wav")
    assert downloaded.content[:4]==b"RIFF"
    approved=client.post(f"/api/projects/{pid}/movie-pipeline/stages/audio/approve",json={"note":"Audio checked"})
    assert approved.status_code==200
    assert next(s for s in approved.json()["stages"] if s["stage"]=="gameplay")["state"]=="READY"

def test_audio_build_rejects_empty_and_duplicate_cues(tmp_path,monkeypatch):
    client,pid,_=ready_audio(tmp_path,monkeypatch)
    empty=client.post(f"/api/projects/{pid}/movie-pipeline/audio/build",json={"cues":[],"music":None})
    assert empty.status_code==400
    duplicate=client.post(f"/api/projects/{pid}/movie-pipeline/audio/build",json={"cues":[
        {"id":"same","label":"A"},{"id":"same","label":"B"}]})
    assert duplicate.status_code==400
