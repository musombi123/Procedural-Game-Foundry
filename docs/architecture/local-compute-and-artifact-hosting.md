# NEXORA local compute and finished-game hosting

## Non-negotiable execution boundary

**The creator's computer is the production machine. NEXORA cloud is the control plane and finished-game distribution layer.**

The hosted API must not store or process projects, story briefs, source movies, source images, raw 3D assets, intermediate renders, Blender jobs, GPU inference, Godot assembly or game exports. Project and workspace API routes are local-only. The cloud API remains available for NEXORA authentication, plan and payment operations, and the future finished-artifact publishing contract.

The cloud middleware rejects project/workspace routes with HTTP 409 and the LOCAL_COMPUTE_REQUIRED machine-readable code. The same Foundry application is mounted beneath /engine by the Local Compute Agent and executes on the creator's computer.

## Device workflow

1. The creator signs in to their separate NEXORA account.
2. The creator installs and starts the local agent on their computer.
3. The local agent binds to 127.0.0.1:8765 and prints a one-time 8-digit pairing code. The code expires after 15 minutes.
4. NEXORA Studio sends the code and the authenticated cloud access token to the local agent. The agent verifies the account against the cloud HTTPS /api/v1/auth/me endpoint.
5. The local agent issues a distinct 12-hour device token. The device token and cloud account token are kept in process/browser session memory only; restarting the local agent invalidates the device token.
6. The Studio requests local CPU, RAM, disk, GPU/VRAM and installed-tool information, then checks the selected workload profile.
7. Project, scene, source-media, asset-conversion, generation, job, validation, playtest and export requests go to the local Foundry API mounted at /engine.
8. For Android, the local agent lists ADB devices, optionally pairs over a private LAN, checks the APK package ID, asks for installation confirmation, installs and launches the game, and returns app-process logs.

## Hardware profiles

These are conservative preflight baselines, not guarantees of performance. Large scenes, textures, models and export targets may need more resources.

| Workload | Initial minimum | Dedicated GPU |
|---|---|---|
| 2D / lightweight projects | 2 CPU logical cores, 8 GiB RAM, 10 GiB free disk | Not required |
| Procedural 3D | 4 CPU logical cores, 16 GiB RAM, 30 GiB free disk, Blender and Godot 4 | Recommended, not mandatory for deterministic procedural generation |
| Movie processing | 4 CPU logical cores, 8 GiB RAM, 20 GiB free disk, FFmpeg and FFprobe | Optional for model-assisted analysis |
| Image-to-3D using the current TripoSR profile | 6 CPU logical cores, 16 GiB installed RAM, 6 GiB available RAM, 40 GiB free disk, Blender, Python, configured TripoSR worker and a working PyTorch CUDA runtime | NVIDIA CUDA GPU with at least 6 GiB total and 4 GiB free VRAM |
| Android export and device test | 4 CPU logical cores, 16 GiB RAM, 25 GiB free disk, Godot 4, Java, Android SDK/build-tools, APK inspector and ADB | Not required for export |

No-GPU creators can still use the supported 2D and deterministic procedural workflows. AI image-to-3D must fail closed when the required CUDA GPU or TripoSR installation is missing.

## Windows installation from source

From a cloned Procedural-Game-Foundry repository, start PowerShell in the repository root and run:

~~~~powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install-nexora-local-environment.ps1
~~~~

The installer creates an isolated Python 3.11 environment, installs the local Foundry runtime, and starts the agent. By default project data is stored under %LOCALAPPDATA%\NEXORA\Foundry and agent staging files under %LOCALAPPDATA%\NEXORA\Agent.

The installer does not silently install GPU drivers, CUDA, Blender, Godot, FFmpeg, Java, Android SDK or AI models. Install the tools required by the selected workload, then restart the agent. Optional executable paths can be configured with NEXORA_BLENDER_PATH, NEXORA_GODOT_PATH, NEXORA_FFMPEG_PATH, NEXORA_FFPROBE_PATH, NEXORA_ADB_PATH, NEXORA_JAVA_PATH, NEXORA_APKANALYZER_PATH, NEXORA_AAPT_PATH and NEXORA_NVIDIA_SMI_PATH. Set NEXORA_TRIPOSR_ROOT to the local TripoSR checkout and optionally NEXORA_TRIPOSR_PYTHON to its Python interpreter. The local preflight imports PyTorch in that interpreter and requires torch.cuda.is_available() to be true before it allows image-to-3D generation.

## Hosted API configuration

Never set NEXORA_LOCAL_AGENT=true on Render. That flag is reserved for the local agent process. The hosted API defaults to account/billing/control-plane mode and rejects all project and workspace API paths.

## Finished-game hosting

The current local agent creates and validates game outputs on the creator's device. This branch does not yet contain a durable cloud artifact publisher or object-storage integration. Before claiming public APK/Web/desktop hosting is complete, configure an S3-compatible object store (for example, Cloudflare R2), issue short-lived upload URLs, verify artifact size and SHA-256, store owner/platform/version metadata in Neon, and expose authenticated downloads or a public Web-game URL. Raw source media and intermediate project files must never be accepted by that publisher.

For Web output, publish the complete Godot Web export directory as a static artifact under a versioned path, including its HTML, JavaScript, WASM, PCK and supporting files. For Android and desktop, publish only validated final APK/AAB, installer, AppImage or packaged ZIP artifacts.

## Operational acceptance gates

- Cloud project, workspace, media, conversion and generation routes return 409 LOCAL_COMPUTE_REQUIRED.
- Local agent binds only to loopback; invalid Host/Origin is rejected; one-time pairing and expiry/restart revocation work.
- Hardware preflight reports the real computer resources and installed tools.
- Every queued production job passes the same backend hardware gate as the UI preflight; insufficient available RAM, disk, CPU, tools or free GPU memory returns DEVICE_REQUIREMENTS_NOT_MET before a job is queued.
- The 2D profile works without a dedicated GPU; image-to-3D is blocked without a configured TripoSR worker and a working PyTorch CUDA runtime.
- Story/movie intake, Blender processing, asset conversion, Godot assembly, smoke test and platform exports run in the local user's data directory.
- Android package identity is verified before install; USB and private-LAN wireless ADB testing succeeds on a physical device.
- Final APK/Web/desktop artifacts upload to durable object storage, retain owner/platform/version/hash metadata, and survive Render restarts.
- Cross-account artifact access is denied.

## Current implementation status

This branch adds the local compute agent, account-bound pairing, hardware preflight, a local Foundry engine mount, cloud-side project/workspace route blocking, and a Windows source installer. The final durable artifact-publishing service and a real-machine end-to-end acceptance run remain release gates. Do not describe the feature as fully deployed or production-verified until those gates pass.