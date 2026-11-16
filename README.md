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
