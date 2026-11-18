# Nexora Foundry release engineering

This directory contains the repeatable export entry point for an assembled Godot game.

## Export targets

An assembled project includes presets for Linux desktop (Linux/X11, x86_64), Windows desktop (Windows Desktop, x86_64) and Android (arm64-v8a and armeabi-v7a).

The presets are public project configuration. Never commit .godot/export_credentials.cfg, release keystores, passwords, signing certificates or other credentials.

## Local build

Install Godot 4.6 and matching export templates, then assemble and validate a game through the Foundry pipeline. Export a development build:

    python scripts/release/export_game.py --project ./path/to/game --target linux --output ./dist/release
    python scripts/release/export_game.py --project ./path/to/game --target android --output ./dist/release

Windows builds use --target windows. Use --mode release only after setting up platform production signing credentials. Android requires GODOT_ANDROID_KEYSTORE_RELEASE_PATH, GODOT_ANDROID_KEYSTORE_RELEASE_USER and GODOT_ANDROID_KEYSTORE_RELEASE_PASSWORD; Windows requires a signing identity and signing tool. Development APKs use the debug signing configuration.

For Android, install OpenJDK 17 and the Android SDK. Set JAVA_HOME and ANDROID_SDK_ROOT (or ANDROID_HOME). Required SDK packages are Android platform 35, platform-tools, build-tools 35.0.1, command-line tools, NDK r28b and CMake 3.10.2.4988404. The exporter configures Godot's per-user editor settings from those environment paths.

## Release outputs and gates

The exporter checks the platform file signature or APK archive structure, hashes every produced artifact, writes release-manifest.json and checksums.sha256, and creates a deterministic ZIP for desktop builds. A successful CI export means the package was produced and structurally validated. It does not replace a creator playtest, actual-device test, code-signing review or store submission review.

--mode debug is suitable for internal creator testing. It is not a public production release. --mode release fails closed when required signing credentials are absent.

## Quality gates

1. Pipeline stages approved by the creator.
2. Godot scene import and headless runtime checks passed.
3. Blender-to-Godot generated-asset integration passed.
4. Export preset and platform toolchain preflight passed.
5. Export artifact exists, has valid platform structure and passes checksum generation.
6. Creator must complete a real playtest on desktop and an actual Android device before approval for distribution.
7. Public/store release requires its own signed build and release authorization.
