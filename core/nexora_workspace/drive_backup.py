"""User-authorized Google Drive backup integration for the NEXORA Local Agent.

OAuth refresh tokens are stored only in the operating system credential vault.
Project archives are uploaded with Drive's resumable upload protocol and are
tagged with the authenticated NEXORA owner and project ID.
"""
from __future__ import annotations

import http.client
import json
import os
import secrets
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request as UrlRequest, urlopen
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from core.nexora_workspace.desktop_factory import (
    BACKUP_TOTAL_LIMIT,
    SNAPSHOT_ID_RE,
    _atomic_json,
    _project_folder,
    _safe_restore_archive,
    _sha256_file,
    _utc,
)

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
DRIVE_SERVICE = "NEXORA Desktop Factory"
DRIVE_REFRESH_KEY_PREFIX = "google-drive-refresh:"
DRIVE_UPLOAD_CHUNK = 8 * 1024 * 1024
_DRIVE_LOCK = RLock()
_PENDING_AUTH: dict[str, dict[str, Any]] = {}
_ACCESS_CACHE: dict[str, tuple[str, float]] = {}


def _keyring():
    try:
        import keyring
    except ImportError as exc:
        raise HTTPException(503, "The local OS credential-vault package is unavailable. Reinstall the NEXORA Local Agent.") from exc
    try:
        backend = keyring.get_keyring()
        if float(getattr(backend, "priority", 0)) <= 0:
            raise RuntimeError("No operating-system credential vault is configured.")
    except Exception as exc:
        raise HTTPException(503, "NEXORA cannot access an operating-system credential vault on this computer.") from exc
    return keyring


def _client_id() -> str:
    value = os.environ.get("NEXORA_GOOGLE_OAUTH_CLIENT_ID", "").strip()
    if not value:
        raise HTTPException(503, "Configure your own Google OAuth Desktop application and set NEXORA_GOOGLE_OAUTH_CLIENT_ID in the Local Agent environment.")
    return value


def _redirect_uri() -> str:
    # Google Desktop OAuth loopback redirects use only the loopback host and
    # port (no arbitrary callback path). The outer Local Agent owns this root.
    value = os.environ.get("NEXORA_GOOGLE_DRIVE_REDIRECT_URI", "http://127.0.0.1:8765").strip()
    parsed = urlparse(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.port != 8765
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise HTTPException(503, "Google Desktop OAuth must redirect to http://127.0.0.1:8765 (the NEXORA Local Agent loopback address).")
    return "http://" + (parsed.hostname or "127.0.0.1") + ":8765"


def _store_refresh_token(owner: str, token: str) -> None:
    keyring = _keyring()
    try:
        keyring.set_password(DRIVE_SERVICE, DRIVE_REFRESH_KEY_PREFIX + str(owner), token)
    except Exception as exc:
        raise HTTPException(503, "The OS credential vault rejected the Google Drive refresh token. No token was written to project or browser storage.") from exc
    with _DRIVE_LOCK:
        _ACCESS_CACHE.pop(str(owner), None)


def _get_refresh_token(owner: str) -> str | None:
    keyring = _keyring()
    try:
        return keyring.get_password(DRIVE_SERVICE, DRIVE_REFRESH_KEY_PREFIX + str(owner))
    except Exception as exc:
        raise HTTPException(503, "Could not read the Google Drive credential from the OS vault.") from exc


def _token_request(data: dict[str, str]) -> dict[str, Any]:
    body = urlencode(data).encode("utf-8")
    request = UrlRequest(
        "https://oauth2.googleapis.com/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=25) as response:
            payload = json.loads(response.read(256 * 1024).decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read(4096).decode("utf-8", errors="replace")
        raise HTTPException(502, "Google OAuth token exchange failed: " + detail[:700]) from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise HTTPException(502, "Could not reach Google's OAuth token service.") from exc
    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise HTTPException(502, "Google OAuth did not return a usable access token.")
    return payload


def _access_token(owner: str, *, force_refresh: bool = False) -> str:
    owner = str(owner)
    with _DRIVE_LOCK:
        cached = _ACCESS_CACHE.get(owner)
        if not force_refresh and cached and cached[1] > time.time() + 90:
            return cached[0]
    refresh_token = _get_refresh_token(owner)
    if not refresh_token:
        raise HTTPException(409, "Connect Google Drive before using off-device backup.")
    data = {
        "client_id": _client_id(),
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    client_secret = os.environ.get("NEXORA_GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    if client_secret:
        data["client_secret"] = client_secret
    payload = _token_request(data)
    access = str(payload["access_token"])
    expires = time.time() + max(120, int(payload.get("expires_in") or 3600))
    with _DRIVE_LOCK:
        _ACCESS_CACHE[owner] = (access, expires)
    return access


def _google_request_json(method: str, url: str, owner: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    token = _access_token(owner)
    headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    request = UrlRequest(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=45) as response:
            result = json.loads(response.read(2 * 1024 * 1024).decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 401:
            _access_token(owner, force_refresh=True)
            return _google_request_json(method, url, owner, payload)
        detail = exc.read(4096).decode("utf-8", errors="replace")
        raise HTTPException(502, "Google Drive API request failed: " + detail[:700]) from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise HTTPException(502, "Could not complete the Google Drive API request.") from exc
    if not isinstance(result, dict):
        raise HTTPException(502, "Google Drive returned an unexpected response.")
    return result


def _drive_upload_resumable(archive: Path, owner: str, project_id: str, snapshot_id: str) -> dict[str, Any]:
    size = archive.stat().st_size
    digest = _sha256_file(archive)
    metadata = {
        "name": "NEXORA-" + project_id + "-" + snapshot_id + ".zip",
        "mimeType": "application/zip",
        "description": "NEXORA local project backup. Restore only into the matching NEXORA project owner.",
        "appProperties": {
            "nexoraOwnerId": str(owner),
            "nexoraProjectId": str(project_id),
            "nexoraSnapshotId": str(snapshot_id),
            "nexoraSha256": digest,
        },
    }
    token = _access_token(owner)
    url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&fields=id,name,size,modifiedTime,webViewLink,appProperties"
    request = UrlRequest(
        url,
        data=json.dumps(metadata).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "application/zip",
            "X-Upload-Content-Length": str(size),
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=45) as response:
            upload_url = response.headers.get("Location")
    except HTTPError as exc:
        if exc.code == 401:
            _access_token(owner, force_refresh=True)
            return _drive_upload_resumable(archive, owner, project_id, snapshot_id)
        detail = exc.read(4096).decode("utf-8", errors="replace")
        raise HTTPException(502, "Could not start the Google Drive resumable upload: " + detail[:700]) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise HTTPException(502, "Could not start the Google Drive resumable upload.") from exc
    if not upload_url:
        raise HTTPException(502, "Google Drive did not return a resumable upload URL.")
    parsed = urlparse(upload_url)
    if parsed.scheme != "https" or parsed.hostname not in {"www.googleapis.com", "content.googleapis.com"}:
        raise HTTPException(502, "Google Drive returned an unexpected upload host.")

    connection = http.client.HTTPSConnection(parsed.netloc, timeout=180)
    request_path = parsed.path + (("?" + parsed.query) if parsed.query else "")
    offset = 0
    try:
        with archive.open("rb") as stream:
            while offset < size:
                chunk = stream.read(min(DRIVE_UPLOAD_CHUNK, size - offset))
                if not chunk:
                    raise HTTPException(500, "The local backup archive ended before the expected byte count.")
                end = offset + len(chunk) - 1
                connection.request(
                    "PUT",
                    request_path,
                    body=chunk,
                    headers={
                        "Authorization": "Bearer " + _access_token(owner),
                        "Content-Type": "application/zip",
                        "Content-Length": str(len(chunk)),
                        "Content-Range": f"bytes {offset}-{end}/{size}",
                    },
                )
                response = connection.getresponse()
                response_body = response.read(1024 * 1024)
                if response.status == 308:
                    offset = end + 1
                    continue
                if response.status in {200, 201} and end + 1 == size:
                    result = json.loads(response_body.decode("utf-8"))
                    return result
                if response.status == 401:
                    _access_token(owner, force_refresh=True)
                    raise HTTPException(502, "Google Drive access expired during upload. Retry the upload; the incomplete Drive upload was not recorded as a completed backup.")
                raise HTTPException(502, f"Google Drive resumable upload stopped with HTTP {response.status}: {response_body.decode('utf-8', errors='replace')[:500]}")
    except HTTPException:
        raise
    except (OSError, http.client.HTTPException, ValueError) as exc:
        raise HTTPException(502, "The Google Drive resumable upload was interrupted. The local snapshot remains intact.") from exc
    finally:
        connection.close()
    raise HTTPException(502, "Google Drive did not confirm completion of the full backup archive.")


def _drive_download(file_id: str, destination: Path, owner: str) -> int:
    token = _access_token(owner)
    request = UrlRequest(
        "https://www.googleapis.com/drive/v3/files/" + file_id + "?alt=media",
        headers={"Authorization": "Bearer " + token, "Accept": "application/octet-stream"},
        method="GET",
    )
    total = 0
    try:
        with urlopen(request, timeout=120) as response, destination.open("wb") as output:
            while True:
                chunk = response.read(8 * 1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > BACKUP_TOTAL_LIMIT:
                    raise HTTPException(413, "The Drive backup exceeds the 10 GiB local restore limit.")
                output.write(chunk)
    except HTTPError as exc:
        if exc.code == 401:
            _access_token(owner, force_refresh=True)
            return _drive_download(file_id, destination, owner)
        detail = exc.read(4096).decode("utf-8", errors="replace")
        raise HTTPException(502, "Could not download the selected Google Drive backup: " + detail[:500]) from exc
    except HTTPException:
        destination.unlink(missing_ok=True)
        raise
    except (URLError, TimeoutError, OSError) as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(502, "Google Drive backup download failed. The local project was not changed.") from exc
    return total


def register_drive_backup_routes(app: Any, manager: Any) -> None:
    router = APIRouter(prefix="/api/v1/desktop/drive", tags=["NEXORA Google Drive Backup"])

    @router.get("/status")
    def drive_status(request: Request):
        owner = getattr(request.state, "nexora_user_id", None)
        if not owner:
            raise HTTPException(401, "Sign in to your NEXORA account.")
        configured = bool(os.environ.get("NEXORA_GOOGLE_OAUTH_CLIENT_ID", "").strip())
        connected = False
        if configured:
            try:
                connected = bool(_get_refresh_token(str(owner)))
            except HTTPException:
                connected = False
        return {
            "configured": configured,
            "connected": connected,
            "scope": DRIVE_SCOPE,
            "credential_storage": "operating_system_credential_vault",
            "owner_account_id": str(owner),
            "note": "Only files created by NEXORA are accessible under the narrow drive.file scope.",
        }

    @router.post("/authorize")
    def drive_authorize(request: Request):
        owner = str(getattr(request.state, "nexora_user_id", "") or "")
        if not owner:
            raise HTTPException(401, "Sign in to your NEXORA account.")
        client_id = _client_id()
        redirect_uri = _redirect_uri()
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        import hashlib
        import base64
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
        with _DRIVE_LOCK:
            _PENDING_AUTH[state] = {
                "owner": owner,
                "verifier": verifier,
                "redirect_uri": redirect_uri,
                "created_at": time.time(),
            }
        query = urlencode({
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": DRIVE_SCOPE,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        })
        return {"authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?" + query, "expires_in_seconds": 600}

def handle_drive_callback(request: Request) -> HTMLResponse:
    """Handle Google's installed-desktop loopback redirect at the agent root."""
    state = str(request.query_params.get("state") or "")
    code = str(request.query_params.get("code") or "")
    error = str(request.query_params.get("error") or "")
    with _DRIVE_LOCK:
        pending = _PENDING_AUTH.pop(state, None)
    if not pending or time.time() - float(pending.get("created_at") or 0) > 600:
        raise HTTPException(400, "Google Drive authorization state is invalid or expired. Start the connection again.")
    if error:
        return HTMLResponse(
            "<!doctype html><html><meta charset='utf-8'><title>NEXORA Drive connection</title>"
            "<body style='font:16px system-ui;max-width:640px;margin:12vh auto;padding:24px'>"
            "<h2>Google Drive was not connected</h2><p>Authorization was declined or cancelled. Return to NEXORA Studio and try again.</p>"
            "<p>You may close this tab.</p></body></html>",
            status_code=200,
        )
    if not code:
        raise HTTPException(400, "Google Drive did not return an authorization code.")
    data = {
        "client_id": _client_id(),
        "code": code,
        "code_verifier": str(pending["verifier"]),
        "redirect_uri": str(pending["redirect_uri"]),
        "grant_type": "authorization_code",
    }
    client_secret = os.environ.get("NEXORA_GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    if client_secret:
        data["client_secret"] = client_secret
    payload = _token_request(data)
    refresh = str(payload.get("refresh_token") or "")
    if not refresh:
        refresh = _get_refresh_token(str(pending["owner"])) or ""
    if not refresh:
        raise HTTPException(502, "Google did not issue an offline refresh token. Disconnect this app in your Google account and reconnect with consent.")
    _store_refresh_token(str(pending["owner"]), refresh)
    access = str(payload["access_token"])
    with _DRIVE_LOCK:
        _ACCESS_CACHE[str(pending["owner"])] = (
            access,
            time.time() + max(120, int(payload.get("expires_in") or 3600)),
        )
    return HTMLResponse(
        "<!doctype html><html><meta charset='utf-8'><title>NEXORA Drive connected</title>"
        "<body style='font:16px system-ui;max-width:640px;margin:12vh auto;padding:24px'>"
        "<h2>Google Drive connected</h2><p>Your NEXORA account can now store verified project backups in your Google Drive.</p>"
        "<p>Return to NEXORA Studio and refresh Backup &amp; Versions.</p><p>You may close this tab.</p></body></html>",
        status_code=200,
    )


    @router.post("/disconnect")
    def drive_disconnect(request: Request):
        owner = str(getattr(request.state, "nexora_user_id", "") or "")
        if not owner:
            raise HTTPException(401, "Sign in to your NEXORA account.")
        keyring = _keyring()
        try:
            keyring.delete_password(DRIVE_SERVICE, DRIVE_REFRESH_KEY_PREFIX + owner)
        except Exception:
            pass
        with _DRIVE_LOCK:
            _ACCESS_CACHE.pop(owner, None)
        return {"disconnected": True}

    @router.post("/projects/{pid}/snapshots/{snapshot_id}/upload")
    def upload_snapshot(pid: str, snapshot_id: str, request: Request):
        folder = _project_folder(manager, pid, request)
        if not SNAPSHOT_ID_RE.fullmatch(snapshot_id):
            raise HTTPException(400, "Invalid local snapshot ID.")
        archive = folder / "backups" / (snapshot_id + ".zip")
        metadata_path = folder / "backups" / (snapshot_id + ".json")
        if not archive.is_file() or not metadata_path.is_file():
            raise HTTPException(404, "Create a local snapshot before uploading it to Google Drive.")
        try:
            snapshot = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise HTTPException(500, "Local snapshot metadata is unreadable.") from exc
        if _sha256_file(archive) != snapshot.get("sha256"):
            raise HTTPException(409, "Local snapshot integrity check failed. The archive was modified.")
        result = _drive_upload_resumable(archive, str(request.state.nexora_user_id), pid, snapshot_id)
        record = {
            "provider": "google_drive",
            "drive_file_id": result.get("id"),
            "name": result.get("name"),
            "size_bytes": result.get("size"),
            "web_view_link": result.get("webViewLink"),
            "snapshot_id": snapshot_id,
            "project_id": pid,
            "sha256": snapshot["sha256"],
            "uploaded_at": _utc(),
        }
        drive_meta = folder / "backups" / (snapshot_id + ".drive.json")
        _atomic_json(drive_meta, record)
        return {"uploaded": True, "backup": record}

    @router.get("/projects/{pid}/backups")
    def list_drive_backups(pid: str, request: Request):
        _project_folder(manager, pid, request)
        owner = str(request.state.nexora_user_id)
        query = "trashed = false and appProperties has { key='nexoraProjectId' and value='" + pid + "' } and appProperties has { key='nexoraOwnerId' and value='" + owner + "' }"
        url = "https://www.googleapis.com/drive/v3/files?" + urlencode({
            "q": query,
            "pageSize": "100",
            "orderBy": "modifiedTime desc",
            "fields": "files(id,name,size,modifiedTime,webViewLink,appProperties),nextPageToken",
        })
        result = _google_request_json("GET", url, owner)
        return {"files": result.get("files", [])}

    @router.post("/projects/{pid}/backups/{file_id}/restore")
    def restore_drive_backup(pid: str, file_id: str, request: Request):
        folder = _project_folder(manager, pid, request)
        if not file_id or len(file_id) > 200 or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in file_id):
            raise HTTPException(400, "Invalid Google Drive file ID.")
        owner = str(request.state.nexora_user_id)
        metadata = _google_request_json(
            "GET",
            "https://www.googleapis.com/drive/v3/files/" + file_id + "?fields=id,name,size,appProperties",
            owner,
        )
        properties = metadata.get("appProperties") or {}
        if str(properties.get("nexoraOwnerId") or "") != owner or str(properties.get("nexoraProjectId") or "") != pid:
            raise HTTPException(404, "Google Drive backup not found for this NEXORA project owner.")
        expected_sha = str(properties.get("nexoraSha256") or "")
        staging = folder / "backups" / ("drive-download-" + uuid.uuid4().hex + ".zip")
        try:
            size = _drive_download(file_id, staging, owner)
            if expected_sha and _sha256_file(staging) != expected_sha:
                raise HTTPException(409, "Downloaded Google Drive backup failed its SHA-256 integrity check.")
            if not zipfile.is_zipfile(staging):
                raise HTTPException(415, "The selected Drive file is not a valid NEXORA backup ZIP.")
            with zipfile.ZipFile(staging, "r") as archive:
                try:
                    manifest = json.loads(archive.read("NEXORA_BACKUP_MANIFEST.json").decode("utf-8"))
                except (KeyError, ValueError, UnicodeDecodeError) as exc:
                    raise HTTPException(422, "The Drive archive has no valid NEXORA backup manifest.") from exc
            if str(manifest.get("project_id") or "") != pid:
                raise HTTPException(403, "The backup belongs to a different NEXORA project.")
            restored = _safe_restore_archive(staging, folder)
            return {
                "restored": True,
                "project_id": pid,
                "drive_file_id": file_id,
                "downloaded_bytes": size,
                **restored,
            }
        finally:
            staging.unlink(missing_ok=True)

    app.include_router(router)
