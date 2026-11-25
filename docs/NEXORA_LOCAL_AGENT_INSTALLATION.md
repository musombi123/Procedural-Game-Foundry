# NEXORA Local Agent for Windows

The Local Agent is the local compute companion used by NEXORA Studio for creator-device workloads. End users install it through the **NEXORA Local Agent Setup** Windows application. They are not expected to use Git, Python, PowerShell commands, or source checkouts.

## End-user installation flow

1. In NEXORA Studio, open Device Lab and choose **Download for Windows**.
2. Open `NEXORA-Local-Agent-Setup.exe` and approve the Windows installation prompt.
3. The per-user installer places the companion under the current Windows profile, includes its own Python runtime and dependencies, and starts the Local Agent in the background.
4. The installer offers to start the Local Agent automatically on future Windows sign-ins. This option is enabled by default.
5. Return to Device Lab and choose **Check connection**. Once the health endpoint is available, choose **Allow & connect this computer** to approve the signed-in NEXORA account.

The website never tries to start an executable or run a script on the user's behalf. The one-time OS installation approval is the security boundary.

## Installer build and release

The Windows installer is built on a Windows GitHub Actions runner by:

- installing the Foundry Python dependencies into the payload;
- bundling the matching official Python 3.11 embeddable runtime;
- bundling the Local Agent source and runtime assets;
- compiling a per-user setup executable with Inno Setup 6;
- producing a SHA-256 checksum alongside the executable.

The workflow uploads the setup executable as a CI artifact for pull-request validation. To publish a customer-downloadable versioned release, push a tag named `nexora-local-agent-vX.Y.Z` after the installer change has been reviewed and merged. The workflow publishes these fixed asset names:

- `NEXORA-Local-Agent-Setup.exe`
- `NEXORA-Local-Agent-Setup.exe.sha256`

NEXORA Studio downloads the first asset from the latest GitHub Release. A release must exist before the customer download link can deliver a file.

## Runtime and security boundaries

- The Local Agent binds to `127.0.0.1:8765` only; it is not a public inbound server.
- CORS origins and the Host header are allow-listed by the Local Agent.
- The browser must be signed in to the NEXORA account. Pairing requires the user to select **Allow & connect this computer**.
- The cloud account session is verified by the NEXORA account API before a short-lived, in-memory local bearer session is issued.
- The local bearer session is invalidated when the agent restarts or its 12-hour lifetime expires.
- The installer runs under the current Windows user and does not request administrator privileges.
- Hardware discovery is local. Optional external tools such as Blender, Godot, FFmpeg, Android SDK/ADB, Java, and CUDA are detected rather than silently installed.

## Important release note

The current setup executable is not Authenticode-signed unless a publisher certificate is configured in the repository's protected CI secrets. To enable signing, store the base64-encoded PFX as `NEXORA_WINDOWS_CODESIGN_PFX_BASE64` and its password as `NEXORA_WINDOWS_CODESIGN_PFX_PASSWORD`. The build signs and verifies the executable before calculating its checksum. Without these secrets, CI emits an unsigned setup executable and logs a warning; Windows may show an unknown-publisher warning.

The SHA-256 file detects accidental or malicious asset changes only when the checksum is obtained through a trusted channel; it does not replace publisher signing. Configure a valid organization-controlled Authenticode certificate before broad public distribution.
