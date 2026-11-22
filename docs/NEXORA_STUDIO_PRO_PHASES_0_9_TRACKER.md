# NEXORA Studio Pro — Phases 0–9 execution tracker

**Working branch:** `nexora-studio-pro-phases-0-9`  
**Base:** `main`  
**Execution rule:** preserve the existing FastAPI + React + Blender + Godot + paired local-agent architecture. No duplicate asset database, no hosted media/game processing, and no paid infrastructure introduced by this work.

## Phase 0 — Repository audit and change boundary

**Status: audited.**

The existing product is not a blank slate. The repository already contains:
- FastAPI workspace and movie-pipeline APIs.
- React/TypeScript workspace, movie pipeline and 3D preview.
- A project-local AssetRegistry and generated movie-pipeline folders.
- Blender procedural character/environment/prop generation.
- Godot scene assembly, playtest and export routines.
- A paired loopback Local Agent, hardware/toolchain inventory, selected local project root, local snapshots and publishing readiness.
- Creator Flow plan catalogue and Pochi receipt-claim/manual-verification routes.

The verified asset-display defect was a split between the registered asset library at `assets/` and generated artifacts under `movie_pipeline/`. The workspace collection endpoint listed only the first location.

## Phase 1 — Asset Collection Center

**Status: asset API fix and collection improvements committed; runtime acceptance still pending.**

Changes in this branch:
- Merge supported files from the existing `movie_pipeline/` tree into the asset listing as read-only generated entries; do not copy them into a second registry.
- Serve generated artifacts through the owner-checked project asset route with path containment checks.
- Keep creator uploads in the existing AssetRegistry and retain its rights/provenance metadata.
- Add a collection UI with search, category filters, re-scan, upload, preview, and scene-use indicators.
- Add unit coverage for registered and generated assets.

Generated entries are currently read-only in the collection. Deletion is not exposed for generated pipeline outputs because their lifecycle belongs to the pipeline revision/approval process.

## Phase 2 — Local Engine and device readiness

**Status: local consent API and a fail-closed production workload gate are implemented; UI and runtime controls remain.**

Existing implementation includes a paired loopback agent, pairing authority, local-only execution policy, selected project root, hardware/toolchain inventory and workload preflight. The hosted API rejects local-compute-only production routes.

Remaining work:
- First-run Device Access Bond UI with purpose and permission summary.
- Enforce the stored consent before every production workload path; current workload preflight now blocks local production work unless the paired Local Agent bond is enabled and returns the selected CPU/RAM/GPU ceilings.
- User-adjustable CPU/RAM/GPU workload ceilings and a visible pause/resume control.
- Runtime resource telemetry and a revocation workflow.
- Signed installer/update acceptance and Windows hardware acceptance.

No browser-only claim is made that a web tab can reserve or safely govern all device CPU/GPU/RAM resources.

## Phase 3 — Level Manager

**Status: local project manifest API implemented; Studio UI and export integration remain.**

The paired desktop API now reads and writes an owner-checked, project-local ordered level manifest with unique IDs, difficulty, draft/testing/approved state, and shared asset IDs. The manifest is stored under the local project `.nexora/levels.json`; no game content is uploaded to Render. Tests cover ordering, shared asset de-duplication, invalid IDs/states/difficulties and the 100-level limit. Remaining work: Level Manager UI, level duplication/deletion/reordering controls, level-specific scene state and multi-level export/resume integration.

## Phase 4 — Export Center

**Status: local build foundations exist; Studio Pro Export Center UI and acceptance remain.**

Existing local factory and workspace APIs support project preparation, Godot export targets, Android signing preflight, release manifests, backups and publishing readiness. The main workspace still needs the dedicated target/configure/build/deliver experience, pre-export validation summary, artifact history and target-specific guidance.

## Phase 5 — Pricing, Pochi and export authorization

**Status: Pochi checkout and manual receipt verification exist; export-token enforcement remains.**

Existing Creator Flow routes:
- Read configured plan prices and the configured Pochi merchant destination.
- Create pending checkout references.
- Accept a customer M-Pesa receipt claim.
- Keep access pending until a privileged reconciliation endpoint verifies the claim.
- Activate an entitlement only after verification.

Remaining work:
- Export-specific quotes and transparent line-item calculator.
- Expiry/duplicate-receipt protections and administrator reconciliation UX.
- Signed, short-lived, single-use export authorization consumed by the Local Engine.
- Server-enforced gating for every paid export target, not only Creator Flow generation actions.
- Receipts and export history metadata.

A user-submitted transaction code is not proof of payment and must never activate an entitlement by itself. The privileged verification endpoint now also requires the independent merchant-side received-payment code and amount; it compares the normalized transaction code exactly with the customer's claim and checks the invoice amount before activation.

## Phase 6 — Plans and monetization add-ons

**Status: partial.**

Creator Flow has a plan catalogue and workload/platform validation. A single source-of-truth entitlement registry across web, desktop, exports and add-ons is still required. AdMob, billing-provider add-ons, subscriptions, paywall configuration, restore purchases and requirements-to-module mapping are not yet complete.

## Phase 7 — Premium Studio interface

**Status: partial foundation only.**

The current workspace has project overview, movie pipeline, world editing, scene editing and asset collection. The requested persistent timeline, Level Manager, Export Center, right inspector/task/resource dock, keyboard shortcuts, undo/redo, tour and responsive premium layout remain.

## Phase 8 — Sponsored placements and advertiser reporting

**Status: not implemented.**

No ad/campaign system or advertiser reporting is claimed. Future implementation must keep placements out of the editing canvas, timeline, preview and active jobs; enforce the supplied frequency caps; label sponsored content; and keep campaign reporting separate from game/project files.

## Phase 9 — Security, recovery and acceptance

**Status: partial foundation.**

Existing controls include owner-bound project operations, path traversal/symlink protections in desktop file APIs, local-only production execution, upload size/format validation, snapshot validation/restore, and owner-scoped job artifacts. Remaining acceptance includes export-token replay tests, payment race/duplicate receipt tests, crash-recovery checkpoints, exportable diagnostics, local-agent bridge security review, and end-to-end acceptance on a real supported desktop.

## Current feature-branch acceptance gates

- [ ] Python unit and integration suite passes.
- [ ] React/TypeScript production build passes.
- [ ] Blender-to-Godot asset pipeline passes.
- [ ] Native export CI job passes.
- [ ] On-device check confirms generated player/environment/props appear in Asset Collection Center and previews load through the local API.
- [ ] No Render/server storage or processing of source videos, project assets, generated game files or exports is introduced.

This tracker deliberately separates existing foundations, code delivered in this branch, and uncompleted acceptance gates. A feature is not considered complete because a route, UI label or architecture document exists.
