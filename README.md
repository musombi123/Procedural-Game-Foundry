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

**Current boundary:** rights-gated uploads and deterministic FFmpeg/FFprobe media inspection are implemented. The worker writes metadata, scene-cut candidates and sampled keyframes. No speech, vision or language models are loaded; the creator supplies story/dialogue context directly.

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

## Creator-led, tools-only movie-to-game workflow

The creator may start with an original written story, a movie clip, or a movie clip plus detailed instructions. A full-body portrait is the mandatory player identity reference: the player avatar is generated from procedural geometry and must remain linked to that portrait throughout the project. A movie is optional in story-first mode and required in movie-first/guided modes.

This workflow is deliberately **model-free**: no Ollama, LLM, image-generation model, image-to-3D model, paid API, or hosted inference endpoint is used. FFmpeg/FFprobe perform media inspection; deterministic code builds the story manifest from creator-authored fields; Blender constructs actual 3D meshes and exports GLB. The system does not invent plot details the creator did not provide.

- Save a creator brief with `PUT /api/projects/{id}/movie-pipeline/story`.
- Retrieve it with `GET /api/projects/{id}/movie-pipeline/story`.
- Build and export the procedural 3D environment with `POST /api/projects/{id}/movie-pipeline/environment/build`. Blender must be installed locally; the endpoint writes a geometry specification and invokes the Blender builder to produce `environment.glb`.
- The Blender builder can also be run directly: `blender --background --python blender/scripts/build_movie_world.py -- --spec world-spec.json --output environment.glb`.

The environment builder creates a heightfield terrain mesh, modular 3D landmarks/structures, procedural props, lighting and a camera. Collision/navigation metadata is included in the world specification for the game-runtime integration step. The creator must review the resulting world before it is used in the final game.

**Current implementation boundary:** creator story input and deterministic world specification/Blender GLB export are implemented in this workstream. The player-character generator/portrait-to-proportional-avatar rig, full navigation mesh baking, actor/prop behavior, mission scripting and end-to-end playable assembly remain subsequent stages. A single photo cannot reveal hidden body geometry; the procedural avatar must use adjustable proportions and creator review rather than claiming exact 3D reconstruction.
