# NEXORA Foundry Desktop

NEXORA Foundry is the desktop-first game-production workstation. It wraps the React/Three.js creator workspace in a Tauri 2 shell. Godot and Blender remain separate native production tools; Android games are exported from the desktop editor and tested on connected Android devices.

## Local services

The desktop shell currently expects the local FastAPI Foundry service to be started separately. From the repository root:

    python -m pip install -e ".[dev]"
    python -m uvicorn services.api.main:app --host 127.0.0.1 --port 8000

The API is intentionally bound to loopback. It provides the Build Console's local Godot process, Android SDK export, ADB device and artifact-history endpoints. These endpoints are not exposed when the API runs in hosted mode.

The web workspace is built from apps/web. The default API base URL is http://127.0.0.1:8000; override it with VITE_PGF_API when needed.

## Native toolchain

Install Godot 4 and matching export templates, Blender for asset work, OpenJDK 17, and the Android SDK components documented in docs/desktop-build-console.md. Godot/Blender/Android SDK workloads run on the creator's desktop; the Android phone is the target/test device, not the editor host.

## Packaging boundary

The Tauri shell is configured for Windows, Linux and macOS bundles, but the Python API is not yet bundled as a managed Tauri sidecar or one-click installer. A standalone installer still needs a packaged Python runtime/API service and prerequisite detection before it can be called a self-contained release.

Desktop build history and generated Android packages currently remain in the local project data folder. Synchronization of those desktop release records and packages into Neon Postgres/private Object Storage is not yet implemented. The authenticated cloud workspace remains a separate cloud path.
