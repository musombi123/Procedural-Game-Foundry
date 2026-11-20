#!/usr/bin/env python3
"""Upload a verified NEXORA Android App Bundle to a creator-owned Play Console app.

This script uploads to the selected Play track only after an interactive
confirmation. It does not create the store account or app record and does not
claim that Google Play has approved or published the release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="Path to a NEXORA release manifest JSON file.")
    parser.add_argument("--project-dir", required=True, help="Local NEXORA project directory containing the artifact path.")
    parser.add_argument("--track", default="internal", choices=("internal", "alpha", "beta", "production"))
    parser.add_argument("--status", default="draft", choices=("draft", "completed"))
    parser.add_argument("--language", default="en-US")
    args = parser.parse_args()

    manifest_path = Path(args.manifest).expanduser().resolve()
    project_root = Path(args.project_dir).expanduser().resolve()
    service_account = os.environ.get("NEXORA_PLAY_SERVICE_ACCOUNT_FILE", "").strip()
    package_name = os.environ.get("NEXORA_PLAY_PACKAGE_NAME", "").strip()

    if not manifest_path.is_file():
        print("Release manifest was not found.", file=sys.stderr)
        return 2
    if not project_root.is_dir():
        print("Project directory was not found.", file=sys.stderr)
        return 2
    if not service_account or not Path(service_account).expanduser().is_file():
        print("Set NEXORA_PLAY_SERVICE_ACCOUNT_FILE to your local Play Console service-account JSON file.", file=sys.stderr)
        return 2
    if not package_name or "." not in package_name:
        print("Set NEXORA_PLAY_PACKAGE_NAME to the existing app's package ID from Play Console.", file=sys.stderr)
        return 2

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"Release manifest is unreadable: {exc}", file=sys.stderr)
        return 2
    if manifest.get("target") != "android" or manifest.get("provider_status") != "prepared_not_submitted":
        print("The manifest is not a prepared Android release.", file=sys.stderr)
        return 2
    artifacts = manifest.get("artifacts") or []
    artifact = next((item for item in artifacts if str(item.get("filename", "")).lower().endswith(".aab")), None)
    if not artifact:
        print("The selected release manifest does not contain an Android App Bundle (.aab).", file=sys.stderr)
        return 2
    relative = Path(str(artifact.get("path") or ""))
    artifact_path = (project_root / relative).resolve()
    if relative.is_absolute() or ".." in relative.parts or project_root not in artifact_path.parents or not artifact_path.is_file():
        print("The AAB path is invalid or outside the selected project.", file=sys.stderr)
        return 2
    if sha256_file(artifact_path) != artifact.get("sha256"):
        print("AAB SHA-256 does not match the release manifest. Refusing upload.", file=sys.stderr)
        return 2

    try:
        from google.oauth2 import service_account as google_service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        print('Install the optional publisher client with: pip install -e ".[publishing]"', file=sys.stderr)
        return 2

    scope = ["https://www.googleapis.com/auth/androidpublisher"]
    try:
        credentials = google_service_account.Credentials.from_service_account_file(
            str(Path(service_account).expanduser()), scopes=scope
        )
        publisher = build("androidpublisher", "v3", credentials=credentials, cache_discovery=False)
        print("NEXORA Play release review")
        print(f"Package:  {package_name}")
        print(f"Track:    {args.track}")
        print(f"Status:   {args.status}")
        print(f"AAB:      {artifact_path}")
        print(f"Bytes:    {artifact_path.stat().st_size:,}")
        print(f"SHA-256:  {artifact['sha256']}")
        print("This requires an existing app and a service account authorized in Play Console.")
        confirmation = "PUBLISH" if args.status == "completed" else "UPLOAD"
        if input(f"Type {confirmation} to create a Play edit and upload this AAB: ").strip() != confirmation:
            print("Cancelled. No Play Console edit was created.")
            return 1

        edit = publisher.edits().insert(packageName=package_name, body={}).execute()
        edit_id = edit["id"]
        media = MediaFileUpload(str(artifact_path), mimetype="application/octet-stream", resumable=True)
        bundle = publisher.edits().bundles().upload(
            packageName=package_name,
            editId=edit_id,
            media_body=media,
        ).execute()
        version_code = bundle.get("versionCode")
        if version_code is None:
            raise RuntimeError("Play Console did not return a bundle version code.")

        notes = str(manifest.get("release_notes") or "Uploaded with NEXORA Desktop Studio.")
        release_name = str(manifest.get("version") or "NEXORA release")
        track_body = {
            "track": args.track,
            "releases": [{
                "name": release_name,
                "versionCodes": [str(version_code)],
                "status": args.status,
                "releaseNotes": [{"language": args.language, "text": notes}],
            }],
        }
        publisher.edits().tracks().update(
            packageName=package_name,
            editId=edit_id,
            track=args.track,
            body=track_body,
        ).execute()
        committed = publisher.edits().commit(
            packageName=package_name,
            editId=edit_id,
            changesNotSentForReview=(args.status == "draft"),
        ).execute()
        print("Play Console edit committed.")
        print(f"Package: {package_name}")
        print(f"Version code: {version_code}")
        print(f"Track: {args.track} ({args.status})")
        print("Google Play review, rollout and availability are separate from this upload.")
        print(json.dumps({"edit_id": edit_id, "version_code": version_code, "committed": bool(committed)}, indent=2))
        return 0
    except Exception as exc:
        print(f"Play Console upload failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
