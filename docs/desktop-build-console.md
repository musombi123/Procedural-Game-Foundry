# NEXORA Desktop Build Console

The Build Console is a desktop-local production feature. Godot, Blender, Java, the Android SDK and ADB execute on the creator's workstation. The hosted NEXORA API is not used as a remote device bridge.

## Current desktop development setup

Run the Python API from the repository root:

    python -m pip install -e ".[dev]"
    $env:PGF_GODOT_BIN = "C:\Tools\Godot\Godot_v4.6.1-stable_win64.exe"
    $env:ANDROID_HOME = "$env:LOCALAPPDATA\Android\Sdk"
    $env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
    $env:JAVA_HOME = "C:\Program Files\Eclipse Adoptium\jdk-17"
    python -m uvicorn services.api.main:app --host 127.0.0.1 --port 8000

On Linux/macOS, set PGF_GODOT_BIN, ANDROID_HOME (or ANDROID_SDK_ROOT) and JAVA_HOME to the installed toolchain paths, then run the same uvicorn command.

In another terminal, start the workspace:

    cd apps/web
    npm install
    $env:VITE_PGF_API = "http://127.0.0.1:8000"
    npm run dev

Open the desktop workspace, create or select a project, and open Build Console. The Tauri shell currently wraps the web workspace; its Python API is still a separately started local process. The API is not yet bundled as a managed Tauri sidecar or one-click desktop installer.

## Android toolchain

Use a Godot editor and matching export templates from the exact same Godot release. The local Build Console checks for the version-specific android_debug.apk, android_release.apk and android_source.zip templates.

For the Godot 4.6 toolchain baseline, install:

- OpenJDK 17.
- Android SDK Platform-Tools 35.0.0 or later.
- Android SDK Build-Tools 35.0.1.
- Android SDK Platform 35.
- Android SDK Command-line Tools (latest).
- Android NDK 28.1.13356709.
- CMake 3.10.2.4988404.

The Build Console detects missing SDK components and reports them before building. NEXORA writes the Android SDK and Java SDK paths into the user-level Godot EditorSettings file before export, while preserving other existing editor preferences.

## Android export settings

The console configures app name, reverse-DNS package ID, version name/code, minimum/target SDK, ARM64/ARMv7 architectures, orientation, launcher icon and manifest permissions.

Upload a square PNG of at least 432×432 pixels. Android adaptive launcher icons require that minimum; keep important artwork inside the icon safe area.

- Debug APK: automatically uses a local Android debug keystore and is suitable for installation and testing.
- Release APK: uses a creator-supplied release keystore and can be installed on a device for a signed release-candidate test.
- Release AAB: invokes Godot's Gradle Android build path. NEXORA installs the matching project Gradle template into game/android/build when absent. AAB files are bundle artifacts, not packages to install directly with adb.

Release signing credentials are sent only to the local API for the duration of that build. Passwords are not written to export presets, project files or build-history records. Back up the release keystore and its password securely; losing them can prevent future updates to an already-published Android application.

## Device test

### USB

1. Enable Android Developer options and USB debugging.
2. Connect the phone to the desktop and accept its RSA authorization prompt.
3. Refresh devices in Build Console.
4. Select the authorized phone, choose a retained APK, install it and launch it.
5. Read Android logcat after launch to inspect runtime errors.

### Wireless debugging

1. Enable Wireless debugging on the phone while it is on the same trusted network as the desktop.
2. Enter the phone IP address, its pairing port, and its six-digit pairing code; select Pair.
3. Enter the separate connection port shown by Android Wireless debugging; select Connect.
4. Refresh devices and select the authorized wireless device.

Wireless ADB should only be enabled on a trusted network. Turn it off when device testing is complete.

## Test, debug and profile

- Validate & FPS test performs a headless Godot import and runtime smoke test, scans the resulting output for script/parse/fatal errors and records FPS samples when the headless renderer reports them.
- Run game launches the generated game in a normal desktop window.
- Debug run launches Godot with verbose debug output.
- GPU / FPS profile launches Godot with profiling and GPU profiling flags; review this live output on the target desktop GPU.
- Open Godot editor opens the generated game project for scene/script corrections. Run validation again after making changes.

Headless FPS is a regression signal, not a replacement for a real GPU profile or a physical Android playtest. A successful APK export is not evidence that the game has passed gameplay, usability, performance or store review.

## Local artifact retention and cloud boundary

For the current desktop-local workspace:

- Exported files are saved below .pgf-data/projects/<project-id>/game/builds/android/.
- The local release index is .pgf-data/projects/<project-id>/build-history.json.
- Each successful build record includes the package identity, version, signing mode, output format, byte size, SHA-256 checksum and signature-verification result.

This local history survives API restarts as long as the project's .pgf-data folder is preserved and backed up. It is not yet synchronized to Neon Postgres or Neon private Object Storage, so it is not a cross-device cloud release vault at this stage. The authenticated cloud workspace and its private object storage remain the separate path for shared cloud project data and cloud worker artifacts; automatic promotion/sync of desktop release builds into that cloud history is a follow-on integration.

The Build Console routes are disabled when PGF_REQUIRE_CLOUD_DEPENDENCIES=true, so the hosted API does not expose desktop process or ADB controls.
