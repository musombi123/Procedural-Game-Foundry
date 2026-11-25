# Nexora Foundry

**Nexora Foundry** is the flagship game-creation product of **NEXORA Interactive Studios**. The studio is an independent creative technology venture and is operationally separate from RevelaCode.


**The flagship game-creation platform from NEXORA Interactive Studios.**

Nexora Foundry is a local-first game creation platform. It converts a versioned Foundry Project Definition (FPD) into a native Godot project using deterministic procedural generators, reusable gameplay components, validation and build tooling. Core generation does not require a neural model or paid AI API.

## Implemented vertical slice
- FastAPI Foundry Core with project, generation-job, validation and Godot-check endpoints.
- Pydantic FPD models and JSON Schemas.
- Deterministic value-noise terrain heightfield.
- Godot 4 assembler producing terrain mesh/collision, player controller, camera and lighting.
- React + TypeScript web project workspace.
- Tauri 2 desktop shell configuration.
- Python tests and GitHub Actions CI.

The production pipeline now includes deterministic Blender asset generation for a procedural avatar, environment, actors/props and original synthesized audio; an approval-gated gameplay compiler; Godot scene assembly; and a Blender-to-Godot integration test. CI uses a synthetic non-identifying portrait fixture only. Real-player likeness review, a founder/creator playtest, device-level Android validation, signed release builds and commercial release hardening remain open gates.


## Creator-led game production pipeline

PGF now includes a rights-gated, persisted seven-stage movie-to-game pipeline manifest and creator approval panel. The workflow captures explicit video/photo rights, likeness consent and original-assets-only confirmation. Stages are locked until the previous stage is approved; regenerating a stage resets its downstream approvals and revisions. See [the pipeline architecture](docs/architecture/movie-to-game-pipeline.md) and [third-party license register](LICENSES.md).

**Current boundary:** rights-gated uploads and deterministic FFmpeg/FFprobe media inspection are implemented. The worker writes metadata, scene-cut candidates and sampled keyframes. No speech, vision or language models are loaded; the creator supplies story/dialogue context directly.

## NEXORA production execution model

## Managed server toolchain and workload placement

NEXORA adds a private managed compute runtime with preinstalled Blender, Godot 4.6.1, FFmpeg/FFprobe, Java 17 and Android SDK/ADB tools. The Local Agent remains useful for project files, local hardware and physical Android devices; light work stays on the user's PC when its live CPU/RAM headroom is safe. Larger supported workloads can be planned for the private worker.

The first stage exposes server capabilities and a placement recommendation. The server workspace uses a Render persistent disk, while local resource figures are shared only if the user explicitly opts in. Without local-resource consent, the planner treats local capacity as unknown and selects the managed worker only when its measured toolchain and capacity pass preflight. The first stage does not upload project files or start remote jobs yet: remote execution remains disabled until the durable queue, per-job transfer approval, ownership controls, and artifact lifecycle are implemented. Heavy rendering and CUDA image-to-3D require separately provisioned higher-capacity/GPU workers.

See [the managed-compute deployment and safety guide](deploy/NEXORA_MANAGED_COMPUTE.md). Do not change the existing account API into a compute worker or set `NEXORA_LOCAL_AGENT=true` on Render.


NEXORA's production compute runs on the creator's own computer. The hosted API is a control plane for account authentication, plans and billing; it does not accept projects, source media, raw assets, GPU jobs, Blender generation or Godot builds. Project/workspace routes on the cloud API are rejected with `LOCAL_COMPUTE_REQUIRED`.

The local agent binds to `127.0.0.1:8765`, uses an expiring one-time pairing code, checks CPU/RAM/free storage/GPU VRAM and installed tools, and exposes the same Foundry engine beneath `/engine`. The web workspace sends project, asset, generation, job and export requests to that paired local engine. Android device installation uses the local ADB bridge.

On Windows, from a cloned repository, run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install-nexora-local-environment.ps1
```

Python 3.11+ is installed into an isolated NEXORA virtual environment. Blender, Godot 4, FFmpeg/FFprobe, Android SDK/ADB, Java and GPU inference workers are detected separately; install only the tools required by the workload. See [the local compute and artifact hosting architecture](docs/architecture/local-compute-and-artifact-hosting.md).

**Deployment status:** the local agent, local-only routing policy, hardware preflight and Windows source installer are implemented on the `nexora-local-compute-p0` feature branch. Durable public hosting of final APK/Web/desktop artifacts requires the separately configured object-storage publishing service and a physical-device acceptance run. Do not set `NEXORA_LOCAL_AGENT=true` on Render.

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

**Current implementation boundary:** creator story input, deterministic world specification/Blender GLB export, and a first procedural humanoid avatar builder are implemented in this workstream. The portrait is used as an identity reference and rough clothing-palette source; it does not provide exact facial reconstruction or hidden anatomy. The avatar has adjustable proportions, a procedural armature, deterministic skin weights and idle/walk animation strips. Full navigation-mesh baking, actor/prop behavior, mission scripting and end-to-end playable assembly remain subsequent stages. A single photo cannot reveal hidden body geometry; the procedural avatar must use adjustable proportions and creator review rather than claiming exact 3D reconstruction.


### Procedural player avatar

After saving a story-first brief (no movie rights or movie upload required) or approving movie analysis, upload a full-body portrait and generate the player through `POST /api/projects/{id}/movie-pipeline/player/build`. Blender builds a skinned humanoid mesh, named deform armature, deterministic proximity weights and idle/walk animation strips. The creator can adjust height, shoulder/hip width, leg proportion, body build and the face-crop rectangle. The cropped portrait face is mapped onto a curved 3D head patch; the generated GLB is shown in an interactive Three.js preview and is available through the project-scoped asset endpoint. The portrait influences a sampled clothing palette and remains the identity reference; the pipeline does not claim to infer a photorealistic face or hidden body shape from one photograph.


## Nexora release status

The Blender-to-Godot integration test runs the repository's actual Blender generators, imports the resulting GLBs and WAV assets into Godot 4.6.1, and exercises the assembled gameplay smoke test. Its synthetic portrait fixture validates the image/texture pipeline only; it does not establish likeness quality.

Assembled games now receive Linux/X11 and Android export presets. A separate CI quality gate attempts both native exports from the same generated game and retains the resulting desktop binary and Android debug APK as build artifacts. These CI exports are reproducibility checks, not a substitute for testing on a physical device or signing a production release.

**Creator acceptance gates still required:** a real full-body portrait supplied with explicit consent; creator review of avatar proportions and face crop; a complete playthrough by a human tester; desktop launch/playtest; Android installation and touch-control playtest; and release signing/packaging. Do not describe the product as production-ready until these gates pass.


## Licence

Original Foundry source and materials are proprietary and all rights are reserved. Third-party software and assets remain under their own licences; consult [LICENSES.md](LICENSES.md) and [LICENSE](LICENSE) before redistribution.

## Repository governance

- [Code of Conduct](CODE_OF_CONDUCT.md)
- [Contributing](CONTRIBUTING.md)

## Licence

Original Nexora Foundry source and materials are proprietary and all rights reserved; see [LICENSE](LICENSE). Third-party software, media, models, fonts, and assets remain subject to their own licences. Use the project's asset/licence register for provenance and redistribution requirements.
