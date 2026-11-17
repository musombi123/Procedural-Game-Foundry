# NEXORA Desktop Device Bridge

The bridge is a local companion for the desktop-first NEXORA game-production workspace. It is not deployed to Render and never exposes ADB over the public internet.

## Responsibilities
- Discover USB and already-paired wireless ADB devices.
- Pair/connect Android 11+ Wireless Debugging devices on a private LAN.
- Install a creator-selected APK after explicit confirmation.
- Inspect the APK archive and manifest application ID before installation.
- Launch the installed package and collect bounded logcat output for that app process.
- Keep device commands and logs on the creator's computer; logs are not uploaded to NEXORA.

## Requirements
- Windows 10/11, macOS or Linux desktop.
- Python 3.11+ for source mode.
- Android SDK Platform Tools (adb) and Android SDK Build Tools (apksigner plus apkanalyzer or aapt).
- Android device with Developer Options and USB Debugging enabled, or Wireless Debugging paired by the creator.

## Run from source
From the repository root:

```powershell
python -m pip install -e ".[desktop]"
python -m nexora_device_bridge
```

The bridge binds only to 127.0.0.1:8765. It prints an eight-digit, one-time pairing code in the desktop terminal. Enter that code in NEXORA's Device Bridge panel. The code is single-use and locks after five failed attempts. Restarting the bridge creates a new code and invalidates the in-memory pairing token.

## Windows executable
With the desktop extra installed:

```powershell
pyinstaller --onefile --name NEXORA-Device-Bridge --collect-all fastapi --collect-all uvicorn --collect-all starlette nexora_device_bridge/__main__.py
```

The executable is written to dist/NEXORA-Device-Bridge.exe. Keep Android SDK Platform Tools and Build Tools installed separately; the bridge does not bundle Google's SDK binaries.

## Device workflow
1. Start the bridge on the creator's desktop.
2. Enter its one-time pairing code in the NEXORA workspace.
3. Connect the phone with USB and approve Android's RSA debugging prompt, or pair Wireless Debugging on a trusted private Wi-Fi network.
4. Refresh devices and select one whose state is device (not unauthorized or offline).
5. Select the downloaded APK from the current NEXORA build, confirm installation and wait for ADB's result.
6. Launch the package and inspect the app-process logcat.

The local bridge requires human confirmation for every install. It rejects AAB files because app bundles are store-upload artifacts, not directly installable APKs.

## Security boundaries
- Loopback-only bind and loopback peer enforcement.
- Strict Origin allowlist for RevelaCode production domains.
- Host-header validation to reduce DNS-rebinding exposure.
- One-time pairing code, five-attempt lockout, bearer token comparison in constant time.
- No shell invocation; ADB arguments are passed as an argument vector.
- Package IDs and device serials are validated.
- Wireless pairing accepts private LAN addresses only.
- APK package ID is checked against the creator's selected package ID before installation.
- No RevelaCode session, Neon credentials, cloud storage keys or signing keys are stored by the bridge.

This is a local device-control agent. It does not certify gameplay quality, performance, compatibility across device models or store readiness.
