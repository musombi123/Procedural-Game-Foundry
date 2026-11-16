"""Local Ollama vision + story-planning subsystem.

Only loopback Ollama endpoints are accepted. Models must already be installed locally;
this module never downloads weights or falls back to a hosted provider.
"""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import StageId, StageState
from .service import PipelineError, PipelineStore


class IntelligenceError(RuntimeError):
    pass


def _local_ollama_url() -> str:
    raw = os.environ.get("PGF_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise IntelligenceError("PGF_OLLAMA_URL must point to a loopback Ollama server; remote inference is disabled")
    return raw


class OllamaLocalClient:
    def __init__(self, base_url: str | None = None, timeout: int = 300):
        self.base_url = (base_url or _local_ollama_url()).rstrip("/")
        parsed = urllib.parse.urlparse(self.base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise IntelligenceError("Only a local loopback Ollama server is supported")
        self.timeout = timeout

    def _request(self, path: str, payload: dict | None = None) -> dict:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path, data=data,
            headers={"Content-Type": "application/json"} if data is not None else {},
            method="POST" if data is not None else "GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise IntelligenceError(f"Cannot reach local Ollama at {self.base_url}: {exc}") from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise IntelligenceError("Local Ollama returned invalid JSON") from exc

    def installed_models(self) -> set[str]:
        payload = self._request("/api/tags")
        return {item.get("name", "") for item in payload.get("models", [])}

    def require_model(self, model: str) -> None:
        installed = self.installed_models()
        if model not in installed:
            short = model.split(":")[0]
            if not any(name.split(":")[0] == short for name in installed):
                raise IntelligenceError(
                    f"Local model '{model}' is not installed. Install it manually with: ollama pull {model}"
                )

    def generate_json(self, model: str, prompt: str, images: list[bytes] | None = None) -> dict:
        payload: dict[str, Any] = {
            "model": model,
            "stream": False,
            "format": "json",
            "messages": [{"role": "user", "content": prompt}],
            "options": {"temperature": 0.2},
        }
        if images:
            payload["messages"][0]["images"] = [base64.b64encode(item).decode("ascii") for item in images]
        response = self._request("/api/chat", payload)
        content = response.get("message", {}).get("content", "")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            cleaned = re.sub(r"^\s*\x60{3}(?:json)?|\x60{3}\s*$", "", content.strip(), flags=re.I)
            try:
                parsed = json.loads(cleaned)
            except json.JSONDecodeError as exc:
                raise IntelligenceError("Local model did not return valid JSON; regenerate or choose another model") from exc
        if not isinstance(parsed, dict):
            raise IntelligenceError("Local model response must be a JSON object")
        return parsed


def _load_keyframes(analysis_dir: Path, entries: list[dict], max_frames: int = 12) -> tuple[list[bytes], list[dict]]:
    usable = [entry for entry in entries if isinstance(entry, dict) and isinstance(entry.get("path"), str)]
    if len(usable) > max_frames:
        stride = (len(usable) - 1) / (max_frames - 1)
        usable = [usable[round(i * stride)] for i in range(max_frames)]
    images, selected = [], []
    root = analysis_dir.resolve()
    for entry in usable:
        path = (root / entry["path"]).resolve()
        if root not in path.parents or not path.is_file():
            continue
        if path.stat().st_size > 8 * 1024 * 1024:
            continue
        images.append(path.read_bytes())
        selected.append({"index": entry.get("index"), "timestamp_seconds": entry.get("timestamp_seconds")})
    if not images:
        raise IntelligenceError("No readable keyframes are available for local vision analysis")
    return images, selected


def _transcript_context(analysis_dir: Path, transcription: dict) -> str:
    relative = transcription.get("path")
    if not relative:
        return "No transcript is available."
    path = (analysis_dir / relative).resolve()
    if analysis_dir.resolve() not in path.parents or not path.is_file():
        return "Transcript file is missing."
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        segments = data.get("segments", [])
        return "\n".join(
            f"[{item.get('start', 0):.1f}s] {item.get('text', '')}"
            for item in segments[:300]
        )[:18000]
    except (OSError, ValueError, TypeError):
        return "Transcript could not be parsed."


def run_story_intelligence(project_folder: Path) -> dict:
    store = PipelineStore(project_folder)
    document = store.load()
    record = next(item for item in document.stages if item.stage == StageId.ANALYSIS)
    if record.state != StageState.REVIEW:
        raise PipelineError("Media analysis must be in REVIEW before story intelligence can run")
    if not document.source_photo or not document.source_video:
        raise IntelligenceError("Both the player portrait and movie video are required")
    manifest_relative = record.output.get("manifest")
    if not isinstance(manifest_relative, str):
        raise IntelligenceError("Media analysis manifest is missing")
    manifest_path = (project_folder / manifest_relative).resolve()
    pipeline_root = store.folder.resolve()
    if pipeline_root not in manifest_path.parents or not manifest_path.is_file():
        raise IntelligenceError("Media analysis manifest is outside the project pipeline or missing")
    analysis_dir = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    frames, selected_frames = _load_keyframes(analysis_dir, manifest.get("keyframes", []))
    vision_model = os.environ.get("PGF_VISION_MODEL", "qwen2.5vl:7b").strip()
    story_model = os.environ.get("PGF_STORY_MODEL", "qwen2.5:7b-instruct").strip()
    if not vision_model or not story_model:
        raise IntelligenceError("Set PGF_VISION_MODEL and PGF_STORY_MODEL to local Ollama model names")
    record.state = StageState.RUNNING
    record.progress = 5
    record.summary = "Interpreting sampled scenes with local vision and story models"
    record.error = None
    store.save(document)
    try:
        client = OllamaLocalClient()
        client.require_model(vision_model)
        client.require_model(story_model)
        vision_prompt = (
            "You are a film-to-game visual analysis system. Inspect the supplied ordered movie keyframes. "
            "Describe only visible evidence and distinguish observations from uncertain inferences. "
            "Do not identify real people or assume copyrighted character identities. Return JSON with keys: "
            "visual_style, recurring_characters (array of objects with label, visible_description, role_hypothesis, confidence), "
            "locations (array of objects with label, visible_features, mood), important_objects (array), "
            "events (array ordered by frame, with frame_index, timestamp_seconds, description, confidence), "
            "environmental_motifs (array), uncertainty_notes (array). Keep concise and factual."
        )
        vision = client.generate_json(vision_model, vision_prompt, frames)
        photo_key = document.source_photo.get("storage_key", "")
        portrait_path = (project_folder / photo_key).resolve()
        upload_root = (store.folder / "uploads").resolve()
        if upload_root not in portrait_path.parents or not portrait_path.is_file():
            raise IntelligenceError("Player portrait is missing or outside the project upload directory")
        if portrait_path.stat().st_size > 20 * 1024 * 1024:
            raise IntelligenceError("Player portrait exceeds the 20 MB analysis limit")
        portrait_prompt = ("Analyze this creator-supplied full-body portrait as an original game-avatar reference. "
            "Do not identify the person. Return JSON with visible_presentation, silhouette, hair_and_headwear, "
            "clothing_and_footwear, dominant_colors, visible_accessories, pose, distinctive_non-identifying_visual_details, "
            "uncertainties. Describe visible evidence only; do not invent hidden features.")
        portrait_analysis = client.generate_json(vision_model, portrait_prompt, [portrait_path.read_bytes()])
        vision["player_portrait_reference"] = portrait_analysis
        vision_path = analysis_dir / "vision-analysis.json"
        vision_path.write_text(json.dumps({"model": vision_model, "selected_frames": selected_frames, "analysis": vision}, indent=2), encoding="utf-8")

        transcript = _transcript_context(analysis_dir, manifest.get("transcription", {}))
        media = manifest.get("media", {})
        story_prompt = (
            "Create an original, playable game concept inspired by the visual themes and events below. "
            "Do not reproduce a film script, dialogue, named copyrighted characters, logos, exact costumes, "
            "or proprietary worldbuilding. Invent original names, designs and plot details. Ground claims in "
            "the supplied observations; mark uncertain details as assumptions. Return only JSON with keys: "
            "title, logline, genre, tone, art_direction, player_character (object with name, role, motivation, "
            "visual_design, abilities), supporting_characters (array), locations (array), factions (array), "
            "missions (array of objects with id, title, objective, gameplay_mechanics, success_condition), "
            "enemies (array of objects with name, behavior, weakness), items (array), level_progression "
            "(array of objects with level, name, setting, primary_challenge, unlock), core_gameplay_loop, "
            "narrative_arc, originality_notes, assumptions. Produce 4-8 missions and 3-7 levels. "
            "The game must be feasible for a small indie 3D action-adventure prototype.\n\n"
            f"MEDIA METADATA: {json.dumps(media, ensure_ascii=False)[:3000]}\n"
            f"VISUAL ANALYSIS: {json.dumps(vision, ensure_ascii=False)[:16000]}\n"
            f"AVAILABLE TRANSCRIPT: {transcript}"
        )
        story = client.generate_json(story_model, story_prompt)
        required_lists = ("missions", "level_progression", "supporting_characters", "locations", "enemies", "items")
        for key in required_lists:
            if not isinstance(story.get(key), list):
                raise IntelligenceError(f"Story model response is missing the required '{key}' array")
        if not isinstance(story.get("title"), str) or not story["title"].strip():
            raise IntelligenceError("Story model response is missing a game title")
        if not 4 <= len(story["missions"]) <= 8 or not 3 <= len(story["level_progression"]) <= 7:
            raise IntelligenceError("Story model must return 4-8 missions and 3-7 levels; regenerate with a suitable local model")
        story_path = analysis_dir / "storyboard.json"
        story_payload = {
            "status": "ready_for_creator_review",
            "model": story_model,
            "vision_model": vision_model,
            "story": story,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        story_path.write_text(json.dumps(story_payload, indent=2), encoding="utf-8")
        manifest["vision_analysis"] = {"status": "completed", "model": vision_model, "path": str(vision_path.relative_to(analysis_dir))}
        manifest["story_design"] = {"status": "completed", "model": story_model, "path": str(story_path.relative_to(analysis_dir))}
        manifest["generated_at"] = datetime.now(timezone.utc).isoformat()
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        store.mark_review(
            StageId.ANALYSIS,
            {**record.output, "vision_manifest": str(vision_path.relative_to(project_folder)),
             "story_manifest": str(story_path.relative_to(project_folder)),
             "mission_count": len(story["missions"]), "level_count": len(story["level_progression"]),
             "intelligence_status": "completed"},
            f"Local intelligence complete: {len(story['missions'])} missions and {len(story['level_progression'])} levels ready for review",
        )
        return story_payload
    except Exception as exc:
        record.state = StageState.FAILED
        record.error = str(exc)
        record.summary = "Local story intelligence failed"
        store.save(document)
        raise
