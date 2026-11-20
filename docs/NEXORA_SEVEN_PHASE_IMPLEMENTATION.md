# NEXORA seven-phase desktop factory implementation

**Architecture:** static desktop browser UI + paired loopback Local Agent + local Godot-first production engine.  
**Execution boundary:** production files, asset generation, tests and exports execute on the creator's computer. The hosted control plane does not run game workloads.

## Phase 1 — Local workspace and project ownership

The Local Agent now exposes:
- GET /workspace for the active root, locally owned project index and available disk.
- PUT /workspace/root to select an absolute local directory. Existing Foundry project folders are moved only after destination collision checks; no conflicting folder is overwritten.
- POST /workspace/import to import a ZIP containing exactly one Godot project.godot file.
- GET /workspace/projects/{id}/archive to export a portable project ZIP.
- POST /workspace/projects/{id}/open-editor to open an imported or generated project in the detected Godot Editor.

Imported Godot sources are kept under the project's source/ directory. Foundry metadata, ownership markers and source remain on the creator's machine. The stable .nexora/project.json UUID is distinct from the Foundry path ID.

ZIP import rejects path traversal, absolute paths, symbolic links, excessive entry counts, oversized entries, excessive expanded size and suspicious compression ratios. .git, .godot, dependency caches and local backups are excluded from portable archives.

## Phase 2 — Toolchain manager

GET /toolchains reports operating system, architecture, installed tools and workload preflight for 2D, procedural 3D, movie processing, Android export and image-to-3D.

POST /workspace/projects/{id}/toolchain-lock records detected versions, executable paths and SHA-256 hashes for directly accessible binaries up to 512 MiB.

**Intentional safety limit:** this pass detects and locks installed tools; it does not silently install software, accept third-party licences, install GPU drivers/CUDA or fetch Android SDK packages. The UI links to official installers. Each installer and licence acceptance remains creator-controlled. The recorded hash is an integrity fingerprint, not proof of publisher identity.

## Phase 3 — Creation workspaces

The existing Foundry engine remains the single creation backend. The creator can hand off imported projects to the native Godot Editor, while NEXORA's existing Creator Flow, scene, world, asset and project workspaces continue to use the paired local engine. No second scene database or engine was introduced.

## Phase 4 — Test lab

The existing local production queue continues to run Godot validation and headless playtests. Workload hardware gates remain enforced by the Foundry API before jobs are queued. Android physical-device install/logcat remains optional and uses the Local Agent's ADB bridge.

## Phase 5 — Build and export

The existing local build queue supports current Godot Web, Android APK/AAB, Windows and Linux export paths. Android export requires the local JDK/SDK/build tools; release AAB output requires release signing. Export availability is detected locally; the Local Agent does not claim that a missing platform template is installed.

A creator must still run desktop/physical-device acceptance tests and protect signing material locally. Apple packaging requires a Mac/Xcode toolchain; Windows-only machines cannot produce a signed Apple release.

## Phase 6 — Backup and versioning

The Local Agent now creates complete project ZIP snapshots under .nexora/snapshots, stores an index with archive and content hashes, downloads snapshots, verifies hashes before restore, and creates a safety snapshot before a restore. The existing Foundry content-addressed world revisions remain intact.

Google Drive backup remains optional and is reported as unconfigured until the creator's Google OAuth client is supplied and the narrow drive.file consent flow is integrated. Local snapshots and portable ZIP export work without Google Drive.

## Phase 7 — Release and store handoff

GET /publishing/status reports provider prerequisites for Google Play, Apple App Store and Microsoft Store without exposing secrets.

POST /publishing/prepare validates an in-project artifact and prepares a local handoff ZIP with package/version details and SHA-256 integrity metadata:
- Google Play requires an Android .aab.
- Apple App Store requires a signed .ipa and macOS/Xcode.
- Microsoft Store requires an .msix.

**Publishing is not falsely marked complete:** this endpoint prepares a reviewable handoff package only. Store upload/release automation remains gated on creator-owned developer accounts, app records, provider credentials, signing and explicit final confirmation. NEXORA cannot register publisher accounts, agree to store terms or guarantee store approval.

## Verification status

The new backend tests cover ZIP path traversal, symbolic-link rejection and safe portable archive exclusions. GitHub Actions must run on this feature branch, and the frontend production build must pass before merge or deployment. A real Windows-machine acceptance run is still required for directory selection/migration, Godot launch, toolchain discovery, export and restore. Store account and external OAuth integration are separate credential-dependent release gates.
