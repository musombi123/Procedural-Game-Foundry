# NEXORA Desktop Factory — Phase 1–7 delivery map

**Architecture:** static desktop web client + paired loopback Local Agent + local Godot-first production workspace.  
**Last updated:** 2026-11-20  
**Boundary:** production source files, generation, media processing, tests and exports stay on the creator's computer. The hosted API remains the NEXORA identity, billing and entitlement control plane.

## Delivery status

| Phase | Delivered in this implementation | Remaining acceptance gate |
|---|---|---|
| 1. Project workspace and ownership | User-selectable local projects root, persistent local preference, owner-bound project manifest, toolchain lock document, import of existing Godot project folders, safe project file listing/read/write, SHA-256 optimistic save checks | Windows desktop acceptance with several workspaces, external drives, account switching and large projects |
| 2. Toolchain manager | Local inventory for Godot, matching export templates, Blender, FFmpeg, Java 17, Android SDK/ADB and APK inspectors; fixed WinGet package allowlist on Windows; explicit user confirmation; project toolchain lock records host, tool versions and selected export targets | Exact installer version/hash pinning, guided Android SDK component installation and tested macOS/Linux installers |
| 3. Creation workspaces | Existing Creator Flow, asset generation, scene editing, local Godot editor handoff and local job queue are retained; Studio now exposes a Project Factory and local code/file explorer | Full embedded IDE capabilities remain a staged integration; Godot Editor remains the authoritative advanced scene editor |
| 4. Test lab | Generated projects pass Foundry validation before export; imported Godot projects are opened headlessly; local headless Godot playtest jobs and ownership-scoped logs/artifacts are available | Interactive playtest matrix, automated regression fixtures per target, performance budgets and physical device acceptance |
| 5. Build and export | Local job pipeline supports Web, Android APK/AAB and Windows/Linux Godot exports; Android package identity and release-signing gates are enforced; release preparation hashes selected artifacts | Windows release installer/MSIX, macOS/iOS export relay, platform-specific automated signing and end-to-end build verification on supported creator machines |
| 6. Backup and versions | Local snapshot ZIPs, per-file SHA-256 manifest, archive integrity check, safe staged restore, Google Desktop OAuth PKCE, restricted drive.file scope, OS credential-vault refresh-token storage, resumable upload and owner/project-verified Drive restore | Configure the creator-owned Google OAuth Desktop client, complete the loopback callback round-trip, then run real-account upload/interruption/restore acceptance; Linux requires a supported Secret Service keyring |
| 7. Release and publishing | Publisher readiness checks and local release manifests; Google Play AAB upload script and Apple App Store Connect signed-IPA upload script require creator-owned credentials and explicit terminal confirmation | Microsoft Store submission connector and MSIX packaging/signing are not implemented; Apple build/export still requires a creator-owned Mac/Xcode workflow; store accounts, app records, agreements, review and final public release remain creator-owned |

## Local project layout

Each managed project retains the Foundry project engine data and gains a .nexora directory:

    MyGame/
      pgf.json
      nexora_owner.json
      .nexora/
        project.json
        toolchain.lock.json
      game/
        project.godot
        .nexora/
          project.json
          toolchain.lock.json
        scenes/
        scripts/
        assets/
      backups/
      releases/

The project root is selected on the desktop agent. Imported Godot projects are copied; the source directory is not modified. The import excludes .git, .godot, .import, virtual environments, caches and dependency directories. The project itself remains plain Godot source and can be opened in Godot without an active NEXORA subscription.

## Security rules

- The canonical desktop API is mounted in the Foundry application. The cloud execution policy rejects /api/v1/desktop requests; the paired Local Agent exposes the same Foundry application under /engine on loopback.
- All project operations verify the authenticated NEXORA owner marker.
- The file editor is limited to text formats, a 2 MiB per-file cap, project-relative paths and SHA-256 optimistic concurrency checks. Symlinks and path traversal are rejected.
- Import and backup enforce file-count and total-size ceilings. Snapshot restore validates ZIP paths and symbolic-link entries before extraction, restores through a staging directory and retains the snapshot.
- The tool installer accepts only fixed package IDs and uses shell=False; it requires a separate confirmation flag. This initial package installer is Windows/WinGet only.
- Google Drive OAuth uses PKCE and redirects to http://127.0.0.1:8765/drive/oauth/callback. The Local Agent validates the one-time state and stores refresh credentials only in a recognized OS keyring backend; tokens are never stored in browser storage or project files.
- Release checks inspect credential-file presence and platform prerequisites; they never return credentials to the browser and never claim a release has been submitted or approved.

## Optional Google Drive backup setup

The Drive connector uses a Google OAuth **Desktop app** client and the desktop loopback redirect. It requests only the `https://www.googleapis.com/auth/drive.file` scope. This allows NEXORA to create and manage only files created by, or explicitly opened/shared with, this application; it does not grant NEXORA general access to the creator's entire Drive.

1. In the creator's Google Cloud project, enable the Google Drive API and configure the OAuth consent screen. Add the creator as a test user while the app is in Testing mode.
2. Create an OAuth client whose application type is **Desktop app**. Do not use a Web application client for the local agent loopback flow.
3. Set `NEXORA_GOOGLE_OAUTH_CLIENT_ID` in the Windows user environment for the Local Agent. An optional client secret may be set as `NEXORA_GOOGLE_OAUTH_CLIENT_SECRET`; the Desktop app flow does not depend on treating a public client secret as confidential.
4. The default OAuth redirect is `http://127.0.0.1:8765/drive/oauth/callback`. Register this exact loopback redirect in the Google Desktop OAuth client configuration. Restart the Local Agent after changing environment variables.
5. In NEXORA Studio, open Backup & Versions, connect Google Drive, grant consent, return to Studio and refresh. Create a local snapshot, then choose Back up to Drive. Confirm the remote copy appears and test restore into a disposable copy of the project before relying on it for recovery.

The refresh token is stored with the local operating system's credential vault. On Windows this uses the Windows credential backend; macOS uses Keychain; Linux requires a supported Secret Service/KWallet backend. NEXORA rejects plaintext file keyring backends. Drive backup is optional and local snapshots remain available when Drive is disconnected.

## Important limits

This is a substantial product implementation, not a claim of production acceptance on every desktop configuration. The following are still external or unverified:

1. The NEXORA developer's physical Windows machine must run the installer and validate the workspace, toolchains, Godot export templates and actual exports.
2. Android AAB release signing requires the creator's protected keystore. A physical Android device is needed for the final install/playtest gate.
3. Google Drive backup is implemented but remains opt-in: configure NEXORA_GOOGLE_OAUTH_CLIENT_ID in the Local Agent environment, restart the agent, connect the creator's Google account, and verify an upload plus restore. Local snapshots remain available even when Drive is disconnected.
4. Google Play and Apple upload scripts require real creator-owned publisher accounts, app records, local credentials and final terminal confirmation. An uploaded build is not approval or public release. Microsoft Store submission is not implemented.
5. Apple builds require a supported Mac/Xcode workflow; the Apple export target is not part of this release.
6. GitHub Actions must complete the repository's existing Python, web, Godot and Blender/Godot integration gates before merge. No local desktop build is inferred from a passing CI run.

Never move game generation, Blender workloads, Android builds or test runs back to Render to bypass a missing local toolchain.
