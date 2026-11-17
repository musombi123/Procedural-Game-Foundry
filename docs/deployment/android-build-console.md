# NEXORA Android Build Console

The desktop-first NEXORA editor queues Android exports through the authenticated cloud workspace API. The API validates creator settings and stores them in the owner-scoped PostgreSQL job payload. The dedicated worker applies those settings to the Godot Android export preset.

## Supported build configuration

- Application display name and Java package/application ID.
- Version name and monotonically increasing version code.
- APK for direct installation/testing; AAB through Godot's Gradle build path for store submission.
- Debug or release export. Release jobs fail closed unless a protected release keystore path, alias and password are configured on the worker.
- Landscape, portrait or sensor orientation.
- Explicit Internet, camera and microphone permissions (disabled unless selected, except Internet by default).

## Worker prerequisites

The desktop/build worker needs Blender, Godot 4 export templates, Java, Android SDK command-line tools/platform-tools, Android platform/build-tools, and Gradle support for AAB exports. Configure the Android SDK in the worker's Godot editor settings. AAB export additionally requires the Godot Android Gradle build template in the generated project.

Release credentials are worker-side secrets only:

- `GODOT_ANDROID_KEYSTORE_RELEASE_PATH`
- `GODOT_ANDROID_KEYSTORE_RELEASE_USER`
- `GODOT_ANDROID_KEYSTORE_RELEASE_PASSWORD`

Never put keystores or passwords in a project document, browser request, artifact, Git commit or frontend environment variable.

## Validation and release boundary

APK outputs are verified with `apksigner verify`; AAB outputs are verified with `jarsigner -verify`. Build metadata records the selected format, signing mode and SHA-256 checksum. A completed export is not a physical-device acceptance test or store publication.

A browser cannot access a creator's USB cable or local wireless ADB endpoint. Physical-device discovery, install, launch and logcat require the NEXORA desktop companion/agent on the creator's computer. Do not mark device testing passed until that local agent reports a successful install and launch against the exact artifact checksum.
