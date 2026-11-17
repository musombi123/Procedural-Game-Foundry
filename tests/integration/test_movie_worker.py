import json
import shutil
import subprocess
from pathlib import Path

import pytest
from core.movie_pipeline.models import RightsDeclaration, StageId, StageState, new_pipeline
from core.movie_pipeline.service import PipelineStore
from core.movie_pipeline import worker

RIGHTS = RightsDeclaration(has_video_rights=True, has_photo_rights=True, likeness_consent=True, accepts_original_assets_only=True)

def _project(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    store = PipelineStore(folder)
    doc = new_pipeline("project", RIGHTS)
    upload = store.folder / "uploads"
    upload.mkdir()
    video = upload / "source-movie.mp4"
    video.write_bytes(b"fixture")
    doc.source_photo = {"storage_key": "movie_pipeline/uploads/player-portrait.jpg"}
    doc.source_video = {"storage_key": "movie_pipeline/uploads/source-movie.mp4", "sha256": "abc"}
    store.save(doc)
    return folder, store, video

def test_worker_requires_attached_video(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    store = PipelineStore(folder)
    store.save(new_pipeline("project", RIGHTS))
    with pytest.raises(worker.MediaAnalysisError, match="Attach a movie"):
        worker.analyze_project(folder)

def test_worker_creates_manifest_and_moves_analysis_to_review(tmp_path, monkeypatch):
    folder, store, video = _project(tmp_path)
    monkeypatch.setattr(worker, "_probe", lambda path: {"duration_seconds": 12.0, "format_name": "mov,mp4", "size_bytes": 10,
                                                          "video": {"codec_name": "h264", "width": 640, "height": 360}, "audio_streams": 1})
    monkeypatch.setattr(worker, "_scene_times", lambda path, duration: ([2.0, 7.0], "test"))
    def extract(path, out, times):
        out.mkdir(parents=True, exist_ok=True)
        target = out / "keyframe-001.jpg"
        target.write_bytes(b"frame")
        return [{"index": 1, "timestamp_seconds": 2.0, "path": str(target.relative_to(out.parent)), "size_bytes": 5}]
    monkeypatch.setattr(worker, "_extract_frames", extract)
    monkeypatch.setattr(worker, "_extract_analysis_frames", lambda path, out, duration: {
        "fps": 12, "frame_count": 144, "directory": "revision-0/frames_12fps"
    })
    monkeypatch.setattr(worker, "_extract_audio_tracks", lambda path, out, count, duration: [
        {"index": 1, "type": "source_mix", "path": "revision-0/audio/audio-track-01.wav", "size_bytes": 100}
    ])
    monkeypatch.setattr(worker, "_transcribe", lambda path, out: {"status": "skipped", "reason": "test"})
    result = worker.analyze_project(folder)
    assert result["status"] == "media_analysis_complete"
    assert result["analysis_frames"]["fps"] == 12
    assert result["analysis_frames"]["frame_count"] == 144
    assert len(result["audio_tracks"]) == 1
    assert result["original_video_retained"] is False
    assert (store.folder / "analysis/revision-0/analysis.json").is_file()
    current_document = store.load()
    current = current_document.stages[0]
    assert current.state == StageState.REVIEW
    assert current.output["keyframe_count"] == 1
    assert current.output["analysis_fps"] == 12
    assert current_document.source_video["sha256"] == "abc"
    assert current_document.source_video["original_retained"] is False
    assert "storage_key" not in current_document.source_video
    assert not video.exists()

def test_scene_fallback_is_bounded(monkeypatch, tmp_path):
    monkeypatch.setattr(worker.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(worker, "_run", lambda *args, **kwargs: (_ for _ in ()).throw(worker.MediaAnalysisError("bad")))
    times, method = worker._scene_times(tmp_path / "movie.mp4", 3600, limit=8)
    assert method == "even_interval_fallback"
    assert len(times) <= 8

def test_analysis_run_endpoint_queues_job_and_completes(tmp_path, monkeypatch):
    import services.api.main as api
    from fastapi.testclient import TestClient
    monkeypatch.setattr(api, "manager", api.ProjectManager(tmp_path))
    monkeypatch.setattr(api, "analyze_project", lambda folder: {"keyframes": [{"index": 1}]})
    client = TestClient(api.app)
    project = client.post("/api/projects", json={"name": "Worker API"}).json()
    pid = project["id"]
    created = client.post(f"/api/projects/{pid}/movie-pipeline", json={"rights": RIGHTS.model_dump(mode="json")})
    assert created.status_code == 201
    store = PipelineStore(api.manager.path_for(pid))
    document = store.load()
    document.source_photo = {"storage_key": "movie_pipeline/uploads/player-portrait.jpg"}
    document.source_video = {"storage_key": "movie_pipeline/uploads/source-movie.mp4"}
    store.save(document)
    queued = client.post(f"/api/projects/{pid}/movie-pipeline/stages/analysis/run")
    assert queued.status_code == 202
    job = client.get(f"/api/jobs/{queued.json()['id']}")
    assert job.status_code == 200
    assert job.json()["state"] == "COMPLETED"
