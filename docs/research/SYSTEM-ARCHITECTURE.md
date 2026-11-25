# Nexora Foundry — system architecture

**Evidence snapshot:** 25 November 2026  
**Primary sources:** `services/api/main.py`, `services/worker/local_agent.py`, `core/`, `generators/`, `apps/web/`, `runtime/`, project README and architecture documents.

## 1. System objective

Nexora Foundry is a local-first game-production platform. It takes a structured, versioned Foundry Project Definition (FPD), validates the creator's project, resolves dependencies, runs deterministic generation steps, assembles a native Godot project and runs available validation/build checks.

The project architecture deliberately separates the browser control interface, local production compute, and cloud account/control-plane responsibilities.

## 2. Logical architecture

```text
Creator
  |
  v
NEXORA Studio UI
(React / TypeScript)
  |
  +------ HTTPS ------> NEXORA cloud control plane
  |                     identity / account / plans / payment
  |
  +------ paired loopback connection ------+
                                           |
                                           v
                              NEXORA Local Compute Agent
                              127.0.0.1:8765
                                           |
                                           v
                                  Foundry FastAPI Core
                                  mounted under /engine
                                           |
                    +----------------------+-------------------+
                    |                      |                   |
                    v                      v                   v
              Project Engine         Orchestration       Validation
              FPD / manifests         jobs / states       schemas/checks
                    |                      |
                    +-----------+----------+
                                |
                                v
                    Procedural generation tools
                    Python / deterministic routines
                       |          |          |
                       v          v          v
                    Blender   FFmpeg/FFprobe  procedural audio
                       |
                       v
                 Asset Registry / project files
                       |
                       v
                 Godot 4 assembler + runtime
                       |
                       v
                playtest / validation / exports
```

This is a logical flow of responsibility. It does not imply every component is deployed as an independently hosted service.

## 3. Core architectural components

### 3.1 Foundry API

`services/api/main.py` creates a FastAPI application and connects project models, project storage, job orchestration, Godot assembly, validation, account identity and local-compute policy. It provides the HTTP interface used by the creator workflow.

The API distinguishes hosted control-plane requests from local-only production operations. When hosted on Render, it must not become a production compute worker even if a local-agent environment flag is accidentally set.

### 3.2 Project Engine and FPD

The project engine stores and retrieves projects using a versioned project model. The Foundry Project Definition is the structured source of truth for project intent and settings. It enables validation and deterministic generation without treating unstructured chat or a model response as an executable project definition.

### 3.3 Job orchestration

The orchestration layer tracks generation and validation jobs and their states. Job state needs to remain observable and recoverable across local process restarts. Persistent job-registry and recovery tests exist in the repository, but production reliability must be validated under realistic interruption and disk-pressure scenarios.

### 3.4 Asset Registry

The project-scoped AssetRegistry stores asset metadata, file references, provenance and validation information. Generated pipeline outputs may reside under dedicated project folders and are surfaced through owner-checked asset endpoints. Do not create a second competing asset database for generated files.

### 3.5 Local Compute Agent

The Local Agent is installed and run on the creator's computer. It binds to loopback at `127.0.0.1:8765`, validates local request origin/host and pairing credentials, reports device capabilities and mounts the Foundry API beneath `/engine`.

The agent provides a controlled device bridge for selected Android ADB operations. It does not expose an unrestricted remote shell and must not accept arbitrary remote filesystem paths.

### 3.6 Blender and media tools

Blender is used for procedural meshes, rigs, environments, actors, props and GLB outputs. FFmpeg/FFprobe handle local media inspection and media processing. The procedural audio subsystem synthesizes original WAV assets using deterministic routines.

### 3.7 Godot runtime and build adapter

Godot 4 is the first supported game engine and the authority for playable output. Foundry produces project data and runtime scripts, assembles native Godot project structures and can invoke configured Godot CLI/headless checks. The browser's Three.js preview is for viewing selected assets and is not the game's authoritative runtime.

## 4. Local and cloud responsibilities

### Local production responsibilities

The Local Agent and Foundry Core on the creator's machine own:

- selected project workspace and raw project files;
- story briefs and local source media;
- Blender generation and asset conversion;
- local job execution and device preflight;
- Godot scene assembly and validation;
- desktop/Android build execution;
- ADB device operations;
- local snapshots and project recovery.

The creator's local project folder is the source of truth and should be exportable/openable outside a live NEXORA session.

### Cloud control-plane responsibilities

The hosted NEXORA API is for account identity, plan/entitlement and payment operations, plus a future finished-artifact distribution contract. The documented architecture rejects cloud project/workspace execution with `LOCAL_COMPUTE_REQUIRED`.

Do not send raw movies, photos, 3D project files, Blender processes, GPU workloads or Godot build jobs to Render.

## 5. Identity, pairing and trust

The documented Local Agent onboarding is:

1. Creator signs into an independent NEXORA account.
2. Local Agent starts on the creator's computer.
3. Agent displays a one-time pairing code with a limited lifetime.
4. Studio supplies the pairing code and authenticated account token.
5. Agent verifies account identity with the cloud HTTPS auth endpoint.
6. Agent issues a separate short-lived device token.
7. Studio uses that device token for scoped local production requests.

The Local Agent token is not the same identity credential as the cloud account token. A new agent process invalidates the previous in-memory device token. Do not expose pairing codes or device credentials in logs, screenshots, public bug reports or partner presentations.

## 6. Repository map

| Path | Responsibility |
|---|---|
| `services/api/` | FastAPI core entry and HTTP routes |
| `services/worker/` | Local agent, local security, workspace, device profile and workload guard |
| `core/project_engine/` | Project and world models/manager |
| `core/orchestration/` | Job lifecycle and coordination |
| `core/generation/` | Generation orchestration and generation contracts |
| `core/asset_registry/` | Project asset registration and GLTF validation |
| `core/movie_pipeline/` | Creator story/video-to-game workflow services |
| `core/gameplay_compiler/` | Creator-authored gameplay compilation |
| `core/game_assembler/` | Native Godot project assembly |
| `core/build_engine/` | Godot command-line checks and build utilities |
| `core/nexora_workspace/` | Creator workspace, local factory and integration APIs |
| `generators/` | Procedural world, terrain and biome routines |
| `runtime/godot_templates/` | Reusable Godot runtime structure |
| `apps/web/` | React/TypeScript Foundry workspace |
| `blender/` | Blender scripts and asset-generation resources |
| `tests/` | Unit, integration, generation, gameplay and export checks |

## 7. Data lifecycle

A project request should be traceable through these stages:

- account is authenticated;
- device is paired and allowed for the requested workload;
- project and selected workspace are owner-scoped;
- request payload passes schema and size validation;
- generation job records its stage and state;
- output is written only beneath the approved project data root;
- asset metadata records path, provenance, generator and checksum;
- validation checks references and file integrity;
- creator reviews and approves staged outputs;
- Godot assembly consumes approved assets and contracts;
- output manifest identifies the build and source project revision.

Any shortcut that allows imported content to write arbitrary paths or execute automatically violates the documented trust model.

## 8. Architecture decisions to preserve

- One versioned FPD source of truth.
- The creator's computer is the production machine.
- Godot remains the supported first game engine.
- Blender and media tools execute locally.
- Project files remain exportable and creator-controlled.
- Local browser-to-agent calls require explicit pairing and origin checks.
- Generated scripts are fixed templates and require review; untrusted imported projects are never automatically executed.
- Asset sources, licences and hashes are recorded.
- Cloud hosting is not a substitute for local game-production compute.
