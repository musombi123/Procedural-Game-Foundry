# NEXORA release and publishing connectors

NEXORA prepares release manifests on the creator's computer. It does not create publisher accounts, accept legal agreements, or automatically submit a build for public release.

## Optional Google Drive backup

Drive backup uses a Google OAuth Desktop application and the narrow
`https://www.googleapis.com/auth/drive.file` scope. NEXORA stores the Google
refresh token in the computer's operating-system credential vault through
Python keyring; short-lived access tokens and PKCE state remain in Local Agent
process memory.

Before connecting Drive:

1. Create an OAuth client in your Google Cloud project with application type
   **Desktop app** and enable the Google Drive API.
2. Set these environment variables in the same Windows/macOS/Linux session
   that starts NEXORA Local Agent:
   - `NEXORA_GOOGLE_OAUTH_CLIENT_ID`: your Desktop OAuth client ID.
   - `NEXORA_GOOGLE_OAUTH_CLIENT_SECRET`: client secret, when provided by
     Google for that client.
3. Restart NEXORA Local Agent and open Backup & Versions in NEXORA Studio.
4. Select Connect Google Drive, complete the Google consent screen, return to
   NEXORA and refresh the connection status.
5. Create a local snapshot, then choose Upload to Drive. Restore is available
   only for backups associated with the selected NEXORA project.

The fixed loopback callback is
`http://127.0.0.1:8765/drive/oauth/callback`. The Local Agent must be running
on the same computer during authorization.

**Backup format:** NEXORA uploads a ZIP archive over HTTPS. The Drive refresh
token is protected by the operating-system credential vault, but NEXORA does
not currently apply a separate client-side password/encryption layer to the
project archive. Treat the Drive copy as containing your project source and
assets; use the access controls of your Google account.

## Google Play Console (Android AAB)

1. Create and verify your own Google Play developer account and create the app record with its final package name.
2. In Play Console, grant a dedicated service account the narrow permissions needed to manage releases for that app. Keep its JSON key on your computer.
3. Install the optional publisher client in the NEXORA virtual environment: pip install -e ".[publishing]".
4. Set local environment variables:
   - NEXORA_PLAY_SERVICE_ACCOUNT_FILE: local service-account JSON file path.
   - NEXORA_PLAY_PACKAGE_NAME: existing Play app package ID.
5. Build a signed Release AAB in NEXORA. Open Release Center and prepare a release manifest after confirming distribution rights.
6. Run the desktop publisher from the repository root. Example in PowerShell:

   $env:NEXORA_PLAY_SERVICE_ACCOUNT_FILE = "C:\secure\play-publisher.json"
   $env:NEXORA_PLAY_PACKAGE_NAME = "com.example.mygame"
   python scripts/nexora-publish-google-play.py --manifest "C:\path\to\project\.nexora\build-manifests\rel_....json" --project-dir "C:\path\to\project" --track internal --status draft

The script validates the AAB hash, asks for a final upload confirmation, uploads to the chosen Play track and commits a draft release. A completed rollout is a separate decision; start with internal and draft.

## Apple App Store Connect

Apple distribution requires a Mac with Xcode, a creator-owned Apple Developer Program membership, an App Store Connect app record, signing certificates and a signed IPA. Export and sign the IPA with Xcode on that Mac. Set the local variables NEXORA_APPLE_API_KEY_PATH, NEXORA_APPLE_KEY_ID, and NEXORA_APPLE_ISSUER_ID, then run scripts/nexora-publish-apple.sh /absolute/path/to/signed.ipa.

The script asks for an explicit upload confirmation and uses Apple's Xcode command-line uploader. Build processing, App Review submission and release are separate actions in App Store Connect.

## Microsoft Store

The current Windows export is an EXE package, not an MSIX. NEXORA therefore reports Microsoft Store publication as not ready until the project has a valid MSIX package, signing certificate and Partner Center identity. Complete the first app identity/listing setup in your own Partner Center account. Do not upload an EXE while claiming it is a Store-ready MSIX.

## Credential and ownership rules

- Service-account JSON, Apple .p8 keys, signing keystores and publisher tokens must stay on the creator's computer. Never commit them, put them in project manifests, or send them to Render.
- NEXORA's optional Google Drive refresh token is stored via the operating system credential vault through Python keyring; access tokens are memory-only.
- A release manifest records the local artifact path, byte size and SHA-256. The digest verifies the artifact bytes; it does not independently establish copyright ownership.
- Upload success is not store approval, a public rollout, or a guarantee that a store will accept the package.
