# Nexora Studio Pro — Phases 0–9 implementation register

Repository: `musombi123/Procedural-Game-Foundry`
Implementation branch: `nexora-studio-pro-phases-0-9`
Baseline: `main` at the time this branch was created.

This register distinguishes verified existing code, changes made on this branch, and work that remains. A phase is not accepted merely because a route, component shell, or design document exists.

## Phase 0 — Repository audit and change manifest

**Status: audited.**

Preserve the existing FastAPI project engine, versioned project definitions, Godot assembler/runtime, Blender procedural generators, movie-pipeline approval state machine, AssetRegistry, local compute agent, and existing workspace adapters. Do not create a second project database or replace Godot.

Key integration points:
- `core/asset_registry/registry.py` — local asset manifest and checksums.
- `core/nexora_workspace/api.py` — workspace API, shared asset listing, project jobs and export flow.
- `core/movie_pipeline/` — creator-approved movie-to-game generation stages.
- `services/api/main.py` — cloud/local execution boundary and route registration.
- `services/worker/local_agent.py` and `services/worker/workload_guard.py` — device pairing and workload preflight.
- `apps/web/src/App.tsx`, `MoviePipelinePanel.tsx`, and builder components — current creator UI.
- `apps/desktop/` — Tauri desktop shell.
- `tests/` and `.github/workflows/` — automated verification.

Change policy: extend existing modules and preserve current API contracts. The creator's machine remains the production compute and project-data owner; hosted services remain control-plane services.

## Phase 1 — Asset Collection Center and asset visibility

**Status: implementation added; Python and web CI pass on the latest checked commit; Godot/Blender integration and local-device acceptance are still pending.**

- The existing asset endpoint previously returned only AssetRegistry records under `assets/`. Generated movie-pipeline files were stored under `movie_pipeline/`, so player and environment GLBs could be successfully generated yet remain absent from the shared collection.
- `core/nexora_workspace/api.py` now includes supported generated GLB/glTF, WAV/OGG/MP3 and image artifacts in the same read model, without copying files or creating a second registry.
- The asset-file route resolves generated-artifact IDs within the project movie-pipeline directory and retains path-containment checks.
- `apps/web/src/AssetCollectionCenter.tsx` adds search, type filters, local upload, rescan, status, file-size, scene-use indication, GLB preview, image preview and audio playback.
- `apps/web/src/App.tsx` mounts the collection in the selected project workspace.
- `tests/test_generated_asset_collection.py` covers generated and registered assets in one collection.

Acceptance still required: run the CI suite and a local end-to-end generation with Blender; confirm generated player/environment/audio assets appear and preview/download successfully.

## Phase 2 — Local Engine and Device Access Bond

**Existing foundation: present; full product acceptance pending.**

The repository already has a loopback local agent, expiring pairing code, account verification, local engine mount, device-token handling, CPU/RAM/storage/GPU/toolchain preflight, and server-side workload guard. The hosted API blocks local-compute routes. Remaining work: explicit first-run Device Access Bond consent, revocation/settings UI, adjustable resource caps, live resource telemetry, pause/resume controls, signed installer verification and cross-platform installer acceptance. The current React App still defaults to port 8000 and uses direct fetch calls; it does not yet complete the browser-to-agent pairing/token flow to the agent's `127.0.0.1:8765/engine` mount. The desktop CSP also needs to be aligned with that bridge. Therefore the existing agent is a foundation, not a finished PC Studio experience.

## Phase 3 — Level Manager

**Status: not yet implemented as the requested level system.**

Existing movie pipeline stages and Godot gameplay/mission compilation are not equivalent to a multi-level manager. Add level manifests, level ordering/difficulty/test state, shared character/asset references, level-specific generation, all-level export and level-number resume metadata without storing game content in the cloud.

## Phase 4 — Export Center

**Existing foundation: partial.**

The workspace has local Godot export jobs and target presets for Windows, Linux, Web and Android. The requested dedicated Export Center still needs the complete target/configure/local-build/deliver workflow, iOS project generation, clean-folder/GitHub-ready export, preflight report, export history metadata and polished UI.

## Phase 5 — Pricing, Pochi reconciliation and signed export activation

**Status: not accepted as implemented.**

Implement one server-owned price calculator and payment ledger, manual Pochi transaction-code submission, admin verification against owner-side statements/SMS, single-use transaction codes, confirmed-payment-only signed export tokens, expiry, replay protection, rate limits and downloadable receipts. Do not trust client-supplied amount/account values. Daraja STK remains a future adapter. No payment or paid service is to be initiated by this implementation.

## Phase 6 — Monetization add-ons and plans registry

**Status: not accepted as implemented.**

Implement one plans/entitlements registry shared by web and desktop, server-enforced plan checks, AdMob IDs and placement configuration, Google Play Billing / StoreKit or RevenueCat configuration, paywall and restore-purchase templates, custom requirements mapping and transparent add-on pricing. Exported games must use creator-owned ad and billing accounts.

## Phase 7 — Premium Studio UI

**Status: partial existing UI; requested redesign pending.**

The existing dark React workspace and Three.js previews are retained. Remaining work: premium studio shell, timeline and playhead, integrated preview/inspector, pipeline/task/resource bars, keyboard shortcuts, undo/redo, autosave/recovery, responsive accessibility, guided tour and PC-app handoff for workloads beyond browser limits.

## Phase 8 — Advertising and campaign administration

**Status: not accepted as implemented.**

Implement consent-aware ad inventory and campaign management, named slots, sponsor labels, close/why-this-ad controls, frequency caps, premium suppression, lazy loading, click/impression tracking, expiry handling, advertiser reports and CSV/PDF exports. Never place ads in active editing canvases, timelines or running jobs; never interrupt sign-in/payment.

## Phase 9 — Security, recovery and acceptance

**Status: partial existing controls; full acceptance pending.**

Preserve existing project ownership checks, local-only routing, loopback binding, pairing expiry, upload validation, asset path checks, workload guards and project snapshots. Add integration tests for asset listing/preview, level state, pricing, payment reconciliation, single-use export tokens, entitlement enforcement, ads frequency caps, crash recovery and export preflight. Verify no source media or project content is sent to hosted storage.

## Current delivery boundary

This branch contains the Phase 0 audit register and a Phase 1 fix for generated assets missing from the shared asset read model and frontend workspace. Phases 2–9 are explicitly tracked above; existing foundations are not misrepresented as complete product acceptance. Continue in order, run the tests at each gate, and do not mark a phase accepted until its executable tests and local-device checks pass.
