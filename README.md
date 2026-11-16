# Procedural Game Foundry

**Model-free. Procedural. Library-driven. Built to produce playable games.**

PGF is a local-first game creation studio. It converts a versioned Foundry Project Definition (FPD) into a native Godot project using deterministic procedural generators, reusable gameplay components, validation and build tooling. Core generation does not require a neural model or paid AI API.

## Implemented vertical slice
- FastAPI Foundry Core with project, generation-job, validation and Godot-check endpoints.
- Pydantic FPD models and JSON Schemas.
- Deterministic value-noise terrain heightfield.
- Godot 4 assembler producing terrain mesh/collision, player controller, camera and lighting.
- React + TypeScript web project workspace.
- Tauri 2 desktop shell configuration.
- Python tests and GitHub Actions CI.

The Blender automation, full asset catalogue, NPC/quest editors, multiplayer, paired local bridge, cloud collaboration, Android signing and complete cross-platform export presets remain planned extensions. A directory or interface is not considered a finished subsystem.


## Movie-to-game production workflow (foundation)

PGF now includes a rights-gated, persisted seven-stage movie-to-game pipeline manifest and creator approval panel. The workflow captures explicit video/photo rights, likeness consent and original-assets-only confirmation. Stages are locked until the previous stage is approved; regenerating a stage resets its downstream approvals and revisions. See [the pipeline architecture](docs/architecture/movie-to-game-pipeline.md) and [third-party license register](LICENSES.md).

**Current boundary:** rights-gated uploads and a local FFmpeg/FFprobe analysis worker are implemented. The worker writes metadata, scene-cut candidates, sampled keyframes and an optional faster-whisper transcript for creator review. Vision-language story synthesis, Blender automation, generated assets, the browser game runtime and APK packaging remain follow-up work.

## Quick start
Python 3.11+:
```bash
python -m venv .venv
# PowerShell: .venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
uvicorn services.api.main:app --reload
```
Open http://127.0.0.1:8000/docs. POST /api/projects creates a project. POST /api/projects/{id}/generate starts generation. Poll GET /api/jobs/{job_id}. Open the generated game/ folder in Godot 4 and press Play.

Web studio: cd apps/web && npm install && npm run dev. Godot is optional for API-only development but required to run and export games.

See docs/architecture/overview.md, docs/engineering/roadmap.md and docs/user_manual/quickstart.md.
