# NEXORA Desktop Game Development Factory

**Status:** Proposed product and implementation architecture  
**Decision date:** 2026-11-20  
**Depends on:** `nexora-local-compute-p0`  
**Initial engine:** Godot 4.x  
**Initial host priority:** Windows desktop  
**Initial export targets:** Web, Android, Windows desktop

## 1. Product decision

NEXORA is a **desktop-only game development factory**. It is not an Android app, a mobile game editor, or a cloud game-generation service.

The NEXORA website remains a static desktop web application. It provides account access, the Studio interface, project navigation, the IDE experience, build controls, backup controls and publishing workflows. A paired NEXORA Local Agent runs on the creator's own computer and performs every operation that reads/writes the local workspace or invokes a game-development toolchain.

The desktop browser is the control surface. The creator's computer is the production machine.

NEXORA must not use Render CPU/GPU to generate game worlds, run Blender, process movies, perform image-to-3D inference, assemble Godot projects, compile games, or run game tests. Render remains a control plane for identity, entitlements, project metadata, optional sync metadata and finished-artifact distribution where explicitly enabled.

### Non-negotiable boundaries

- NEXORA Studio is supported on desktop operating systems only. Mobile browsers receive a clear unsupported-device message; they do not get a reduced game editor.
- A phone is not required to create or export an Android game. Android SDK, Java, Godot export templates and build tools run on the creator's desktop.
- A phone connection over USB/ADB or wireless debugging is optional and is only for installing and testing a finished APK on a real device.
- Production jobs execute on the creator's selected local workspace and local hardware.
- Cloud APIs do not accept production job payloads as a way to run work on Render.
- Account creation does not silently install software. First-run setup checks the machine, asks which platforms the creator intends to target, explains disk/download requirements and installs only the selected supported toolchains after consent.

## 2. Product architecture

```text
                  NEXORA STATIC DESKTOP STUDIO
              Account • IDE • Projects • Build Center
                    Backup • Release Center
                              |
                     HTTPS account/control APIs
                              |
              NEXORA CLOUD CONTROL PLANE (Render)
             Auth • Billing • Entitlements • Metadata
               Optional sync index • Artifact delivery
                              |
                Paired local session / loopback
                              |
                   NEXORA LOCAL AGENT
             Workspace FS • Job queue • Toolchains
             Device bridge • Process supervision
                              |
       +----------------------+----------------------+
       |                      |                      |
   GODOT ENGINE            BLENDER               FFmpeg
   scenes/scripts         3D assets             movie/audio
       |                      |                      |
       +----------------------+----------------------+
                              |
                  LOCAL BUILD / TEST PIPELINE
                              |
             +----------------+----------------+
             |                |                |
           WEB             ANDROID          WINDOWS
        HTML bundle       APK / AAB       EXE / MSIX
             |                |                |
             +----------------+----------------+
                              |
                 USER-OWNED PUBLISHER ACCOUNTS
         Google Play • Apple App Store • Microsoft Store
```

The existing independent NEXORA account boundary and local-compute P0 work remain the foundation. Do not create another auth system, another project database, or a second game-generation backend.

### Cloud responsibilities

Cloud owns:
- NEXORA account identity, sessions, subscription/payment reconciliation and entitlements.
- Project index and ownership metadata: project ID, owner account ID, display name, local machine registrations, last-sync marker and available backup versions.
- Optional cloud backup/artifact metadata and authenticated download authorization.
- Publisher connection metadata that is safe to retain (provider, account/app identifiers, granted scopes and connection status), never raw signing keys or long-lived publishing credentials.
- Product catalogue, quotas, usage records and support/audit events.

Cloud does not own or execute:
- Godot Editor or project runtime.
- Blender, TripoSR, FFmpeg, image/video processing or asset generation.
- Android SDK/Gradle builds, Windows builds or local test runs.
- The creator's only copy of source files, project assets or signing keys.

### Local responsibilities

The paired local agent owns:
- The selected workspace root and project files.
- Toolchain detection, installation, version pinning and health checks.
- Local project creation, source editing, asset generation, import, conversion, game assembly and exports.
- Process lifecycle, per-job logs, cancellation and disk-space checks.
- Local testing, emulator/device connections and build verification.
- Local Git history, snapshots and recovery.
- Optional upload/download of encrypted backups or finished outputs at the creator's request.

The local agent should expose narrow, typed operations. Do not provide a general-purpose unauthenticated shell endpoint. Process execution must use allowlisted tools, validated arguments, workspace-scoped working directories, resource/time limits and shell-free process invocation.

## 3. Desktop-only user journey

### Step A — Create account

The creator signs up through the desktop NEXORA website. NEXORA creates an independent account and project namespace in the cloud.

The account does not itself install Android Studio, Android SDK, Blender or Godot.

### Step B — Install and pair NEXORA Desktop Agent

The creator downloads a signed installer for the desktop operating system. The first-run wizard:
1. Detects host OS/architecture, CPU, RAM, free disk, GPU/VRAM and installed developer tools.
2. Pairs the computer to the signed-in NEXORA account with a one-time code.
3. Lets the creator select target platforms (Web, Android, Windows; Apple targets only when a supported Mac is available).
4. Displays the exact toolchains, storage requirements, licenses and downloads needed for those targets.
5. Installs or configures the approved toolchain components locally, after explicit consent.
6. Runs smoke checks and stores a local toolchain inventory.

The installer should not download every SDK for every user. Install on demand. Pin tested versions in a toolchain manifest and verify download hashes/signatures. The creator must review and accept third-party SDK and engine licenses where required.

### Step C — Create a project

The creator chooses a local workspace root. Suggested default:

- Windows: `%USERPROFILE%\\Documents\\NEXORA\\Projects`
- macOS: `~/Documents/NEXORA/Projects`
- Linux: `~/Projects/NEXORA`

Allow the creator to change the location, use an external drive and open an existing compatible Godot project.

Each project gets a stable UUID and cloud owner record. Project creation writes to disk first; the cloud stores the index and metadata, not the only copy of the project.

### Step D — Design and generate

A guided Game Design Workbench captures:
- Title, genre, target platforms and rendering profile.
- Core loop, player actions, goals, progression and difficulty.
- Story/world brief, episode/level plan and scene requirements.
- Characters, NPCs, enemies, vehicles, props and environmental assets.
- Audio, accessibility, localization, controls and input modes.
- Rights declarations and provenance for supplied material.

NEXORA converts the approved design into a traceable production plan. Generation is performed by local workers using the local Godot/Blender/FFmpeg toolchain and, where supported, opt-in local inference. Each stage produces files in the active project, logs and a reviewable result. The creator remains in control of approvals.

### Step E — Edit, test and save

NEXORA Studio provides:
- Project explorer and file editor.
- GDScript/code workspace and project-wide search.
- Scene/asset/inspector panels where NEXORA has a stable integration.
- Game preview, local playtest, logs, errors and performance diagnostics.
- A way to open the full Godot Editor for advanced scene work instead of recreating the entire Godot editor and renderer.
- Local snapshots, Git history, restore points and project validation.

**Do not build a new game engine or duplicate Godot's mature scene editor.** NEXORA should own the orchestration, AI-assisted design/generation, project experience, workflow, safety checks and publishing pipeline, while Godot remains the first engine runtime/editor/export backend.

### Step F — Build and export

The Build Center shows platform readiness, missing toolchains, required signing configuration, build warnings and estimated local resource requirements before it starts. Builds run on the creator's machine and are written into the project output directory.

### Step G — Back up and publish

Local save is always available and remains the source of truth. Google Drive backup is optional and user-authorized. Store publishing is a separate, explicit workflow connected to the creator's own publisher account.

## 4. Workspace and ownership model

A project must remain understandable and usable without an active NEXORA subscription or a running NEXORA server, subject to any separately licensed third-party assets or services.

Suggested project structure:

```text
MyGame/
  project.godot
  .nexora/
    project.json
    toolchain.lock.json
    design/
    provenance/
    build-manifests/
  scenes/
  scripts/
  assets/
    source/
    generated/
    imported/
  audio/
  shaders/
  addons/
  tests/
  exports/
    web/
    android/
    windows/
  backups/
```

The exact engine folder names may follow the generated Godot project layout; NEXORA metadata should not make the project invalid as a normal Godot project.

### Ownership invariants

- The authenticated NEXORA account is the authoritative cloud owner of the project record.
- Every local project has a stable project UUID and the account ID that created or last claimed it. Account ownership checks are enforced by the API, not trusted from browser-supplied IDs.
- A creator can export/copy the raw project folder and continue working in Godot without NEXORA.
- NEXORA does not hold the only copy of a source project or require proprietary cloud execution to reopen it.
- Generated/exported artifacts carry a build manifest containing project UUID, version, platform, engine/toolchain versions, output hashes and asset provenance/license references. A checksum proves integrity, not legal copyright ownership.
- User-provided assets retain their existing license/rights. The product terms must clearly describe the rights granted for NEXORA-generated materials; do not promise ownership of third-party models, fonts, music, datasets or source assets.
- Signing keys, keystores, certificates, Apple API private keys and Microsoft publishing credentials are never written into the normal project manifest or uploaded as ordinary project files.

Local ownership metadata is not a substitute for the legal product terms or license checks. The user must be able to inspect the provenance record for assets that ship with a game.

## 5. Toolchain manager

Maintain a machine-level inventory and a per-project version lock. Do not rely on whatever happens to be installed on PATH without recording its version.

Initial managed tools:

| Component | Purpose | Install policy |
|---|---|---|
| Godot 4.x editor + export templates | Game editor, runtime, import and export | Required for the initial engine |
| Blender | Procedural and imported 3D asset processing | Required for 3D workflows; optional for simple 2D |
| FFmpeg / FFprobe | Video, audio and media processing | Installed only when media workflows are used |
| Python environment | Local tooling and selected asset/inference workers | Isolated per NEXORA toolchain; no global package pollution |
| Java JDK | Android Gradle/export support | Install a tested compatible version for the pinned Godot/Android stack |
| Android SDK Command-Line Tools | Android platforms, build tools, platform tools and optional NDK | Installed only when Android is selected |
| ADB | Optional physical Android device install/debug | Device testing only; no phone required for APK/AAB export |
| Windows packaging/signing tools | Windows executable and Store package preparation | Installed only on supported Windows hosts |
| Git | Local history and optional remote version control | Recommended, not a cloud dependency |

Use Android's official `sdkmanager` to install exact SDK packages into a NEXORA-managed SDK root. Do not require the full Android Studio IDE when command-line tools are sufficient. Godot's current Android export documentation describes SDK/JDK setup and, in current Godot versions, an automatic Android build setup flow; the NEXORA manager should implement its own audited and version-pinned setup rather than assume a single Android SDK version forever.

The first-run wizard may offer a recommended profile such as “Web + Android + Windows”, but it must display the components, disk usage and license prompts before installation. It should support repair, update, rollback and uninstall without deleting the creator's projects.

## 6. Export and publishing matrix

### Initial supported export matrix

| Target | Local build output | Build host | Store route |
|---|---|---|---|
| Web | Static HTML/JS/WASM and asset bundle | Windows, macOS or Linux desktop | User's hosting provider; optional NEXORA deployment connector later |
| Android testing | Signed or debug APK | Windows, macOS or Linux desktop with Android toolchain | Direct install, emulator or optional ADB device install |
| Google Play | Signed Android App Bundle (AAB) | Windows, macOS or Linux desktop with Android toolchain | Google Play Console / Publishing API |
| Windows desktop | EXE plus data/PCK and dependencies | Windows desktop for initial guaranteed support | Direct distribution or MSIX package for Microsoft Store |
| Apple App Store | Xcode project / signed iOS archive and IPA | **macOS with Xcode** | App Store Connect / Transporter / App Store Connect API |

A target must be shown as “unsupported on this computer” when its official toolchain or signing requirements are not met. Do not pretend a Windows machine can produce a final iOS App Store binary. Apple uploads use Xcode, Transporter or App Store Connect API credentials; the actual Apple build/signing workflow requires a Mac/Xcode environment. A later Apple target can use a Mac owned by the creator as a NEXORA Build Relay. It must not silently move the build to Render.

### Web

- Export a complete static web directory, not only an HTML launcher.
- Generate a local preview server so browser security rules and asset paths behave like deployment.
- Run a smoke test for entry file, referenced assets, MIME types and browser console errors.
- Offer ZIP export and a later deploy connector for the creator's own hosting/domain.

### Android

- Android SDK/JDK/Godot templates are installed on the desktop.
- APK is for direct install, emulator or optional device testing.
- AAB is the Google Play submission format.
- Package ID, version code, app icons, orientation, permissions, architecture, minimum API, target API and signing configuration are checked before release.
- Create a keystore locally if the user does not have one; explain that loss of the private signing key can block future updates depending on Play App Signing setup. Store the key in a protected local credential store or an encrypted user-controlled backup. Never send it to NEXORA cloud by default.
- ADB/USB is optional and not part of the build requirement.

### Windows

- Produce a runnable Windows build and its required data/dependency files.
- Add MSIX packaging as a separate release step for Microsoft Store.
- Validate package identity, version, architecture, assets, signature and dependency declarations before upload.

### Apple

- On a non-Mac host, NEXORA can validate project settings and export an Xcode project where the engine supports it, but final Xcode compilation, signing and App Store upload require a supported Mac/Xcode environment.
- Provide a clear Mac requirement and a later user-owned Mac Build Relay; do not use an undocumented cloud Mac build farm or store the user's Apple private key in NEXORA cloud.

## 7. Store connectors and user-controlled release

A publisher connection is not created automatically when someone registers for NEXORA. The creator must first have their own developer/publisher account, accept the platform's legal agreements, register the app/product and grant NEXORA the minimum required access.

Store integration is a Release Center, not an implicit side effect of exporting a game:

1. Check the selected target and local build prerequisites.
2. Collect required store identifiers (package/bundle ID, Store ID, SKU, version).
3. Validate the build and store metadata.
4. Prepare screenshots, descriptions, age-rating answers, privacy disclosures and other store assets.
5. Connect to the user's existing publisher account using the official authentication/API route.
6. Upload a draft or testing release first where supported.
7. Show the exact package/version/account/track and submission summary.
8. Require a final, explicit user confirmation before committing/submitting/releasing.
9. Poll the store's processing/certification status and display the result; NEXORA must not claim that an app is approved just because upload succeeded.

### Google Play

The Publishing API can upload bundles and manage release tracks/edits for apps in the developer's Play account. The API does not create the developer account or perform every initial Console/legal setup step. Start with an existing Play Console app, connect a suitably permissioned service account/API identity and upload to an internal testing or draft track before production rollout.

### Apple App Store

The developer needs an Apple Developer/App Store Connect account, an existing app record, a Mac/Xcode build environment and an API key/role that can perform the required actions. Apple documents uploading with Xcode, Transporter, altool or App Store Connect API/JWT. The creator must still complete Apple's agreements, metadata and review process.

### Microsoft Store

The developer needs a Partner Center developer account and must reserve/create the app identity in Partner Center. Microsoft recommends MSIX for many Windows apps. Its submission API can manage later submissions, but initial product setup and at least the first submission/age-rating steps must be completed in Partner Center first. Keep API credentials scoped to that creator's Partner Center/Azure application.

All publisher API credentials are user-owned secrets. Prefer short-lived OAuth access tokens and OS-protected credential storage. Provide a disconnect/revoke operation. NEXORA may store the provider connection status and non-secret identifiers in the cloud, but not private keys in browser storage or shared project JSON.

## 8. Local and optional cloud storage

### Default: local workspace

- Save projects to the creator's chosen device folder.
- Use local Git or equivalent snapshots for history, branches, diffs and rollback.
- Provide explicit “Open Folder”, “Save Snapshot”, “Export Project Archive” and “Restore” actions.
- Project files stay available when the network or NEXORA cloud is unavailable.

### Optional Google Drive backup

Google Drive is a backup/sync destination, not the only workspace. Use OAuth with the narrow `drive.file` scope and a file picker so the creator grants access to the specific NEXORA archives/files they select. For large project archives, use resumable uploads and report progress/retry state. Do not ask for broad read/write access to every file in a person's Drive.

The backup format should be a versioned NEXORA project archive with a manifest, file hashes, engine/toolchain lock, provenance metadata and an optional client-side encryption layer. Provide restore and conflict detection; never silently overwrite a newer workspace with an older archive.

OneDrive and other providers can be added later behind the same Storage Provider interface. Do not make Google Drive a hard dependency.

### Optional NEXORA cloud backup

Cloud backup/object storage may be offered as a paid convenience, but it must be an explicit user-selected destination with quotas and retention policy. It is not required for local creation or export.

## 9. IDE and Factory workspaces

The desktop NEXORA Studio should expose these coherent workspaces:

1. **Project Center** — create/open/import, recent work, local paths, backups, project ownership and health.
2. **Game Design Workbench** — original game brief, level/episode planning, progression and acceptance criteria.
3. **Asset Factory** — Blender, model conversion, image-to-3D, textures, audio and video processing on local workers.
4. **Code & Scene Studio** — project explorer, source editor, Godot scene workflow and advanced Godot Editor handoff.
5. **Test Lab** — play, automated smoke tests, logs, profiler and optional emulator/device bridge.
6. **Build Center** — Web, Android APK/AAB and Windows targets with separate build presets and local preflight.
7. **Release Center** — package inspection, store metadata, publisher account connections, draft submissions and explicit publish approval.
8. **Backup & Versions** — snapshots, local Git, Drive/cloud backup and restore.

The user should experience one continuous project workspace. Avoid opening independent tools with disconnected project copies; all tools must operate on the same project root and report their outputs back to the same manifest.

## 10. Monetization

Remove AdMob/rewarded-ad logic from NEXORA. The product is a desktop professional development environment, not an ad-supported mobile utility.

Use the independent NEXORA subscription/payment system (including the configured Pochi merchant destination) to sell:
- Plan-based access to advanced factory workflows, templates and asset tools.
- Higher project/backup/version quotas where there is real cloud storage cost.
- Optional collaboration/team features.
- Optional cloud backup/distribution capacity.
- Future optional paid model/provider integrations, with clear disclosure when a third-party inference API is used.

Do not charge a creator merely because a local CPU/GPU job is running on their own computer unless the plan explicitly includes licensed premium capabilities or an optional paid service. Do not invent prices or quotas in code: keep owner-approved values in the server-side price catalogue.

## 11. Delivery phases and acceptance gates

### Phase 0 — Desktop local-compute foundation
- Preserve the existing local-compute P0 boundary and paired local agent.
- Hosted API rejects project-production routes; local agent uses authenticated pairing.
- Render cannot become a production worker through an environment flag.
- The interface states that NEXORA Studio is desktop-only.

**Gate:** a creator can pair a desktop and prove that project/worker execution occurs locally, with no Render generation request.

### Phase 1 — Persistent workspace and ownership
- Workspace root selection and safe project file APIs.
- Stable project UUID, owner enforcement and project manifest.
- Import/open/export raw Godot project folders.
- Local Git/snapshots, crash recovery and restore.

**Gate:** close/reopen NEXORA, restart the machine, go offline and reopen the exact same project without cloud project contents.

### Phase 2 — Toolchain manager
- Host preflight and supported version matrix.
- Install/repair/update/uninstall Godot, templates, Blender, FFmpeg and target-specific SDKs.
- Per-project toolchain lock and integrity checks.
- Explicit license and disk-space prompts.

**Gate:** install a clean machine profile and pass tool self-tests without manual PATH surgery.

### Phase 3 — Godot-first Studio and local generation
- Project explorer, code editing, design workbench and review-gated asset pipelines.
- Godot Editor handoff and local playtest.
- Persist every generated asset and design stage in the project.
- Local logs, cancellation and recovery.

**Gate:** create a small original game end-to-end using only local production processes and reopen the source in Godot.

### Phase 4 — Web, Android and Windows exports
- Web static bundle + local preview + smoke test.
- Android APK + AAB build, signature checks and optional ADB install.
- Windows runnable package + MSIX packaging.
- Export manifests, hashes and repeatable release presets.

**Gate:** build and playtest each target from the same saved source project on supported desktop hosts.

### Phase 5 — Storage and backup
- Local archive/export.
- Google Drive OAuth using `drive.file`, resumable upload and restore.
- Backup version listing, conflict handling and encryption.

**Gate:** back up a project, remove the local working copy in a test environment, restore it and verify every file hash.

### Phase 6 — Store release connectors
- Google Play internal test/draft flow.
- Microsoft Store draft submission flow.
- Apple Xcode/Mac relay design and later implementation.
- Store metadata, policy checklist, account connection and explicit final submit.

**Gate:** a test app is uploaded to a draft/internal track in the creator's own publisher account. Production publishing remains an explicit user action.

## 12. Engineering rules

- Godot is the first supported engine; other engines use future adapters and must not be implied to work until their toolchains/tests exist.
- No full Unity/Unreal editor clone in the initial release.
- Do not store project source as opaque server-only data. Creators must be able to copy and open their project independently.
- Never store signing private keys, keystore passwords or publisher private keys in ordinary project JSON, browser localStorage or NEXORA cloud logs.
- Do not auto-publish to a store. Build, validate, upload draft, then require user confirmation.
- Toolchain versions must be pinned per release and checked against the host OS.
- Do not claim a target is supported until a physical or reproducible host build/test passes.
- Keep all API contracts and the existing independent NEXORA account boundary stable.
- The mobile RevelaCode app is a separate product; do not package NEXORA Studio into it.

## 13. Official implementation references

- Godot Android export and Android SDK/JDK configuration: https://docs.godotengine.org/en/latest/tutorials/export/exporting_for_android.html
- Godot headless command-line export: https://docs.godotengine.org/en/latest/tutorials/editor/command_line_tutorial.html
- Android SDK command-line tools and `sdkmanager`: https://developer.android.com/tools
- Android export formats (APK for testing, AAB for Google Play): https://developer.android.com/games/engines/godot/godot-export
- Google Play Developer Publishing API: https://developers.google.com/android-publisher
- Apple App Store Connect build upload and API: https://developer.apple.com/help/app-store-connect/manage-builds/upload-builds/
- Microsoft Store publishing prerequisites and MSIX guidance: https://learn.microsoft.com/en-us/windows/apps/publish/get-started
- Microsoft Store Submission API: https://learn.microsoft.com/en-us/windows/uwp/monetize/manage-app-submissions
- Google Drive API scopes: https://developers.google.com/workspace/drive/api/guides/api-specific-auth
- Google Drive resumable uploads: https://developers.google.com/workspace/drive/api/guides/manage-uploads

---

**Decision summary:** NEXORA's value is the integrated local game-production workflow and release factory. The hosted website is the desktop control interface; the paired desktop computer owns the engine, tools, workspace, builds and signing material. Cloud storage, Google Drive and store publishing are optional services around that local-first core.
