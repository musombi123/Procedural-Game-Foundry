# NEXORA Desktop Factory — Phase 1–7 delivery map

**Architecture:** static desktop web client + paired loopback Local Agent + local Godot-first production workspace.  
**Last updated:** 2026-11-20  
**Boundary:** production source files, generation, media processing, tests and exports stay on the creator's computer. The hosted API remains the NEXORA identity, billing and entitlement control plane.

## Delivery status

| Phase | Delivered in this implementation | Remaining acceptance gate |
|---|---|---|
| 1. Project workspace and ownership | User-selectable local projects root, persistent local preference, owner-bound project manifest, toolchain lock document, import of existing Godot project folders, safe project file listing/read/write, SHA-256 optimistic save checks | Windows desktop acceptance with several workspaces, external drives, account switching and large projects |
| 2. Toolchain manager | Local inventory for Godot, Blender, FFmpeg, Java, Android SDK/ADB and APK inspectors; fixed WinGet allowlist for Godot, Blender, FFmpeg, Temurin 17 and Android Studio; explicit user confirmation before installing | Exact package-version pinning and hash/signature verification; Godot export-template and Android SDK component setup wizard; tested macOS/Linux installers |
| 3. Creation workspaces | Existing Creator Flow, asset generation, scene editing, local Godot editor handoff and local job queue are retained; Studio now exposes a Project Factory and local code/file explorer | Full embedded IDE capabilities remain a staged integration; Godot Editor remains the authoritative advanced scene editor |
| 4. Test lab | Existing local project validation and headless Godot playtest remain available through the paired agent; project and file ownership checks protect local operations | Interactive playtest matrix, automated regression fixtures per target, performance budgets and physical device acceptance |
| 5. Build and export | Existing local export pipeline supports Web, Android APK/AAB and Windows/Linux Godot exports; release preparation can hash a selected artifact; Web exports are bundled with their supporting files | Windows release installer/MSIX, platform-specific automated signing and end-to-end build verification on supported creator machines; Apple target is not implemented |
| 6. Backup and versions | Local snapshot ZIPs, per-file SHA-256 manifest, archive integrity check, safe restore staging and traversal/symlink rejection | Google Drive OAuth connector and off-device backup/restore are not yet implemented; configure user-owned OAuth before claiming cloud backup |
| 7. Release and publishing | Publisher readiness checks and a local release manifest with owner, target, path, byte count and SHA-256; no credential values are exposed to the web client | Google Play Publishing API, App Store Connect upload and Microsoft Store submission connectors are not yet implemented; store accounts, app records, agreements and final publish approval remain creator-owned |

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

- The desktop factory router is registered only when LOCAL_AGENT_MODE is true. The cloud execution policy rejects /api/v1/desktop requests.
- All project operations verify the authenticated NEXORA owner marker.
- The file editor is limited to text formats, a 2 MiB per-file cap, project-relative paths and SHA-256 optimistic concurrency checks. Symlinks and path traversal are rejected.
- Import and backup enforce file-count and total-size ceilings. Snapshot restore validates ZIP paths and symbolic-link entries before extraction, restores through a staging directory and retains the snapshot.
- The tool installer accepts only fixed package IDs and uses shell=False; it requires a separate confirmation flag. This initial package installer is Windows/WinGet only.
- Release checks inspect credential-file presence and platform prerequisites; they never return credentials to the browser and never claim a release has been submitted or approved.

## Important limits

This is a substantial product implementation, not a claim of production acceptance on every desktop configuration. The following are still external or unverified:

1. The NEXORA developer's physical Windows machine must run the installer and validate the workspace, toolchains, Godot export templates and actual exports.
2. Android AAB release signing requires the creator's protected keystore. A physical Android device is needed for the final install/playtest gate.
3. This implementation does not upload project backups to Google Drive. Local snapshots are not off-device disaster recovery.
4. Store readiness is not store publishing. Store API submission connectors, credentials and app-specific identifiers require additional implementation and creator-owned accounts.
5. Apple builds require a supported Mac/Xcode workflow; the Apple export target is not part of this release.
6. GitHub Actions must complete the repository's existing Python, web, Godot and Blender/Godot integration gates before merge. No local desktop build is inferred from a passing CI run.

Never move game generation, Blender workloads, Android builds or test runs back to Render to bypass a missing local toolchain.
