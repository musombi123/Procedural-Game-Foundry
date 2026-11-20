#!/usr/bin/env bash
# Upload a locally signed IPA to the creator's App Store Connect account.
# Uploading a build is not the same as submitting it for App Review or release.
set -euo pipefail

IPA_PATH="\${1:-}"
if [[ -z "$IPA_PATH" || ! -f "$IPA_PATH" ]]; then
  echo "Usage: scripts/nexora-publish-apple.sh /absolute/path/to/signed.ipa" >&2
  exit 2
fi
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Apple upload requires macOS and Xcode command-line tools." >&2
  exit 2
fi
if ! command -v xcrun >/dev/null 2>&1; then
  echo "Install Xcode command-line tools before uploading." >&2
  exit 2
fi

: "\${NEXORA_APPLE_API_KEY_PATH:?Set NEXORA_APPLE_API_KEY_PATH to the local App Store Connect .p8 API key file}"
: "\${NEXORA_APPLE_KEY_ID:?Set NEXORA_APPLE_KEY_ID from App Store Connect}"
: "\${NEXORA_APPLE_ISSUER_ID:?Set NEXORA_APPLE_ISSUER_ID from App Store Connect}"

if [[ ! -f "$NEXORA_APPLE_API_KEY_PATH" ]]; then
  echo "App Store Connect API key file was not found." >&2
  exit 2
fi

# altool resolves API keys by AuthKey_<KEY_ID>.p8 through API_PRIVATE_KEYS_DIR.
# Stage the supplied key in a private temporary directory and delete it on exit.
KEY_DIR="$(mktemp -d)"
chmod 700 "$KEY_DIR"
cp "$NEXORA_APPLE_API_KEY_PATH" "$KEY_DIR/AuthKey_\${NEXORA_APPLE_KEY_ID}.p8"
chmod 600 "$KEY_DIR/AuthKey_\${NEXORA_APPLE_KEY_ID}.p8"
export API_PRIVATE_KEYS_DIR="$KEY_DIR"
trap 'rm -rf "$KEY_DIR"' EXIT

echo "NEXORA App Store Connect validation"
echo "IPA: $IPA_PATH"
shasum -a 256 "$IPA_PATH"
xcrun altool --validate-app \
  --type ios \
  --file "$IPA_PATH" \
  --apiKey "$NEXORA_APPLE_KEY_ID" \
  --apiIssuer "$NEXORA_APPLE_ISSUER_ID"

read -r -p "Type UPLOAD to send this validated signed build to App Store Connect: " CONFIRM
if [[ "$CONFIRM" != "UPLOAD" ]]; then
  echo "Cancelled. No upload was started."
  exit 1
fi

xcrun altool --upload-app \
  --type ios \
  --file "$IPA_PATH" \
  --apiKey "$NEXORA_APPLE_KEY_ID" \
  --apiIssuer "$NEXORA_APPLE_ISSUER_ID"

echo "Build upload completed. Check App Store Connect processing before any App Review submission."
