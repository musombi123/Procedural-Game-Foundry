"""Local, tools-only media analysis worker for the movie-to-game pipeline."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import StageId, StageState
from .service import PipelineError, PipelineStore

class MediaAnalysisError(RuntimeError):
    pass

def _run(command: list[str], timeout: int = 180, include_stderr: bool = False) -> str:
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise MediaAnalysisError(f"Required local executable is not installed: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaAnalysisError(f"Media command timed out after {timeout} seconds: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc))[-3000:]
        raise MediaAnalysisError(f"{command[0]} failed: {detail}") from exc
    return result.stdout + "\n" + result.stderr

def _probe(video: Path) -> dict[str, Any]:
    raw = _run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(video)], timeout=60)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MediaAnalysisError("ffprobe returned invalid JSON") from exc
    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not video_stream:
        raise MediaAnalysisError("Uploaded movie contains no video stream")
    duration = float(data.get("format", {}).get("duration") or video_stream.get("duration") or 0)
    if duration <= 0:
        raise MediaAnalysisError("Could not determine a valid video duration")
    return {
        "duration_seconds": round(duration, 3),
        "format_name": data.get("format", {}).get("format_name"),
        "size_bytes": int(data.get("format", {}).get("size") or video.stat().st_size),
        "video": {key: video_stream.get(key) for key in ("codec_name", "width", "height", "avg_frame_rate", "pix_fmt")},
        "audio_streams": sum(1 for s in streams if s.get("codec_type") == "audio"),
    }

def _scene_times(video: Path, duration: float, limit: int = 24) -> tuple[list[float], str]:
    limit = max(2, limit)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise MediaAnalysisError("FFmpeg is required for keyframe extraction")
    # FFmpeg's scene score selects likely cuts. showinfo emits timestamps without decoding a full-resolution frame set.
    expression = "select='gt(scene,0.35)',showinfo"
    try:
        output = _run([ffmpeg, "-hide_banner", "-i", str(video), "-vf", expression, "-an", "-f", "null", "-"], timeout=max(180, int(duration * 2)), include_stderr=True)
        times = [float(value) for value in re.findall(r"pts_time:([0-9]+(?:\.[0-9]+)?)", output)]
        method = "ffmpeg_scene_score"
    except MediaAnalysisError:
        times, method = [], "even_interval_fallback"
    if not times:
        count = min(limit, max(1, int(duration // 30) + 1))
        times = [min(duration - 0.05, duration * (i + 0.5) / count) for i in range(count)]
    # Bound output size and ensure deterministic ordering.
    if len(times) > limit:
        stride = (len(times) - 1) / (limit - 1)
        times = [times[round(i * stride)] for i in range(limit)]
    return sorted(set(max(0.0, min(t, duration - 0.05)) for t in times)), method

def _extract_frames(video: Path, output_dir: Path, times: list[float]) -> list[dict[str, Any]]:
    ffmpeg = shutil.which("ffmpeg")
    output_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for index, timestamp in enumerate(times, start=1):
        name = f"keyframe-{index:03d}.jpg"
        target = output_dir / name
        _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", f"{timestamp:.3f}", "-i", str(video),
              "-frames:v", "1", "-vf", "scale='min(1280,iw)':-2", "-q:v", "3", "-y", str(target)], timeout=60)
        if target.is_file() and target.stat().st_size:
            frames.append({"index": index, "timestamp_seconds": round(timestamp, 3),
                           "path": str(target.relative_to(output_dir.parent)), "size_bytes": target.stat().st_size})
    return frames

def _transcribe(video: Path, output_dir: Path) -> dict[str, Any]:
    """No speech-recognition model is loaded in tools-only mode."""
    return {"status": "skipped", "reason": "Tools-only mode: speech transcription models are disabled; provide story/dialogue context in the creator brief"}


def analyze_project(project_folder: Path) -> dict[str, Any]:
    store = PipelineStore(project_folder)
    document = store.load()
    record = next(item for item in document.stages if item.stage == StageId.ANALYSIS)
    if record.state != StageState.READY:
        raise PipelineError("Analysis stage must be READY before the worker can run")
    if not document.source_video:
        raise MediaAnalysisError("Attach a movie video before starting analysis")
    video = (store.folder / document.source_video["storage_key"]).resolve()
    uploads = (store.folder / "uploads").resolve()
    if uploads not in video.parents or not video.is_file():
        raise MediaAnalysisError("Movie source is missing or outside the project upload directory")
    record.state = StageState.RUNNING
    record.progress = 5
    record.summary = "Inspecting source video with local media tools"
    record.error = None
    record.updated_at = datetime.now(timezone.utc).isoformat()
    store.save(document)
    try:
        metadata = _probe(video)
        record.progress = 25
        store.save(document)
        analysis_dir = store.folder / "analysis" / f"revision-{record.revision}"
        analysis_dir.mkdir(parents=True, exist_ok=True)
        times, detection_method = _scene_times(video, metadata["duration_seconds"])
        frames = _extract_frames(video, analysis_dir / "keyframes", times)
        record.progress = 75
        store.save(document)
        transcription = _transcribe(video, analysis_dir)
        result = {
            "status": "media_analysis_complete",
            "source_sha256": document.source_video.get("sha256"),
            "media": metadata,
            "scene_detection": {"method": detection_method, "candidate_count": len(times),
                                "scenes": [{"index": i + 1, "start_seconds": round(t, 3),
                                            "end_seconds": round(times[i + 1], 3) if i + 1 < len(times) else metadata["duration_seconds"]}
                                           for i, t in enumerate(times)]},
            "keyframes": frames,
            "transcription": transcription,
            "vision_analysis": {"status": "disabled_tools_only", "reason": "Visual interpretation is creator-guided; no machine-learning vision models are loaded"},
            "story_design": {"status": "creator_authored", "reason": "Use the creator story editor to define plot, missions and instructions; no generated text is used"},
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        manifest = analysis_dir / "analysis.json"
        manifest.write_text(json.dumps(result, indent=2), encoding="utf-8")
        store.mark_review(StageId.ANALYSIS, {"manifest": str(manifest.relative_to(project_folder)),
                                             "keyframe_count": len(frames), "duration_seconds": metadata["duration_seconds"],
                                             "transcription_status": transcription["status"]},
                          f"Media analysis complete: {len(frames)} keyframes extracted; ready for creator review")
        return result
    except Exception as exc:
        record.state = StageState.FAILED
        record.error = str(exc)
        record.summary = "Local media analysis failed"
        record.updated_at = datetime.now(timezone.utc).isoformat()
        store.save(document)
        raise

