"""Direct-to-workspace 3D asset downloads from the official Poly Haven API.

The downloader only accepts metadata-derived URLs on Poly Haven's API and
download hosts, verifies the provider's MD5, caps file sizes, and writes inside
the selected local Godot project. It never proxies assets through cloud storage.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

API_ROOT = "https://api.polyhaven.com"
API_HOST = "api.polyhaven.com"
DOWNLOAD_HOST = "dl.polyhaven.org"
USER_AGENT = "NEXORA-Desktop-Asset-Library/1.0 (https://revelacode.co.ke)"
MAX_ASSET_BYTES = 250 * 1024 * 1024
ASSET_ID_RE = re.compile(r"^[a-z0-9_]{2,100}$")
RESOLUTIONS = {"1k", "2k", "4k"}


class PolyHavenError(ValueError):
    pass


def _request_json(url: str) -> Any:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != API_HOST:
        raise PolyHavenError("Rejected non-Poly Haven API URL.")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            if urllib.parse.urlparse(response.geturl()).hostname != API_HOST:
                raise PolyHavenError("Poly Haven API redirected to an untrusted host.")
            return json.loads(response.read(40 * 1024 * 1024).decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise PolyHavenError(f"Poly Haven API request failed: {exc}") from exc


def search_models(query: str = "", limit: int = 40) -> dict[str, Any]:
    query = str(query or "").strip().lower()
    if len(query) > 120:
        raise PolyHavenError("Search text is too long.")
    limit = max(1, min(int(limit), 80))
    payload = _request_json(f"{API_ROOT}/assets")
    results = []
    for asset_id, item in payload.items():
        if not isinstance(item, dict) or item.get("type") != 2:
            continue
        tags = item.get("tags") if isinstance(item.get("tags"), list) else []
        searchable = " ".join([
            str(asset_id), str(item.get("name", "")), str(item.get("description", "")),
            str(item.get("category", "")), " ".join(str(tag) for tag in tags),
        ]).lower()
        if query and query not in searchable:
            continue
        results.append({
            "id": asset_id,
            "name": item.get("name") or asset_id.replace("_", " ").title(),
            "description": item.get("description", ""),
            "category": item.get("category", ""),
            "tags": tags[:20],
            "thumbnail_url": item.get("thumbnail_url"),
            "polycount": item.get("polycount"),
            "dimensions": item.get("dimensions"),
            "max_resolution": item.get("max_resolution"),
            "license": "CC0-1.0",
            "source": "Poly Haven",
        })
    results.sort(key=lambda item: (0 if query and query in item["name"].lower() else 1, item["name"].lower()))
    return {"provider": "Poly Haven", "license": "CC0-1.0", "results": results[:limit], "count": min(len(results), limit)}


def _walk_files(node: Any, path: tuple[str, ...] = ()):
    if isinstance(node, dict):
        if isinstance(node.get("url"), str) and isinstance(node.get("size"), (int, float)):
            yield path, node
        else:
            for key, value in node.items():
                yield from _walk_files(value, path + (str(key),))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk_files(value, path + (str(index),))


def _choose_model_files(payload: Any, resolution: str) -> list[tuple[tuple[str, ...], dict[str, Any]]]:
    candidates = []
    for path, record in _walk_files(payload):
        url = urllib.parse.urlparse(record["url"])
        if url.scheme != "https" or url.hostname != DOWNLOAD_HOST:
            continue
        suffix = Path(urllib.parse.unquote(url.path)).suffix.lower()
        if suffix not in {".glb", ".gltf", ".bin", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}:
            continue
        path_text = "/".join(path).lower()
        if resolution not in path_text and resolution not in url.path.lower():
            continue
        score = 0
        if suffix == ".glb":
            score += 100
        elif suffix == ".gltf":
            score += 80
        elif suffix == ".bin":
            score += 30
        else:
            score += 20
        if "gltf" in path_text:
            score += 15
        candidates.append((score, path, record))
    if not candidates:
        raise PolyHavenError(f"No downloadable glTF/GLB model files were published at {resolution}.")
    # Prefer a GLB (self-contained) where available; otherwise retain the
    # selected glTF branch's texture/buffer dependencies.
    candidates.sort(key=lambda item: item[0], reverse=True)
    best_score = candidates[0][0]
    if Path(urllib.parse.urlparse(candidates[0][2]["url"]).path).suffix.lower() == ".glb":
        return [(candidates[0][1], candidates[0][2])]
    selected = [item for item in candidates if item[0] >= best_score - 60]
    # If the metadata contains several format trees, retain only glTF branch.
    gltf = [item for item in selected if "gltf" in "/".join(item[1]).lower()]
    selected = gltf or selected
    # Deduplicate by provider URL.
    unique = {}
    for _, path, record in selected:
        unique[record["url"]] = (path, record)
    return list(unique.values())


def _download_verified(url: str, target: Path, expected_size: int, expected_md5: str) -> int:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != DOWNLOAD_HOST:
        raise PolyHavenError("Rejected untrusted asset download URL.")
    if expected_size <= 0 or expected_size > MAX_ASSET_BYTES:
        raise PolyHavenError("Asset file exceeds the 250 MB per-file download limit.")
    if not re.fullmatch(r"[a-fA-F0-9]{32}", str(expected_md5 or "")):
        raise PolyHavenError("Provider did not supply a valid MD5 checksum; refusing an unverified download.")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    digest = hashlib.md5()
    written = 0
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".nexora-download")
    try:
        with urllib.request.urlopen(request, timeout=60) as response, temp.open("wb") as output:
            if urllib.parse.urlparse(response.geturl()).hostname != DOWNLOAD_HOST:
                raise PolyHavenError("Asset download redirected to an untrusted host.")
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > expected_size or written > MAX_ASSET_BYTES:
                    raise PolyHavenError("Downloaded asset exceeded its declared size.")
                digest.update(chunk)
                output.write(chunk)
        if written != expected_size:
            raise PolyHavenError("Downloaded asset size does not match the provider manifest.")
        if expected_md5 and digest.hexdigest().lower() != expected_md5.lower():
            raise PolyHavenError("Downloaded asset failed the provider MD5 integrity check.")
        temp.replace(target)
        return written
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def download_model(project_root: Path, asset_id: str, resolution: str = "2k") -> dict[str, Any]:
    if not ASSET_ID_RE.fullmatch(str(asset_id or "")):
        raise PolyHavenError("Invalid Poly Haven asset identifier.")
    if resolution not in RESOLUTIONS:
        raise PolyHavenError("Resolution must be 1k, 2k or 4k.")
    metadata = _request_json(f"{API_ROOT}/assets")
    asset = metadata.get(asset_id)
    if not isinstance(asset, dict) or asset.get("type") != 2:
        raise PolyHavenError("The requested Poly Haven asset is not a 3D model.")
    files = _request_json(f"{API_ROOT}/files/{urllib.parse.quote(asset_id, safe='')}")
    selected = _choose_model_files(files, resolution)
    project = project_root.resolve()
    destination = (project / "assets" / "3d" / "polyhaven" / asset_id).resolve()
    if project not in destination.parents:
        raise PolyHavenError("Asset destination escapes the selected Godot project.")
    destination.mkdir(parents=True, exist_ok=True)
    downloaded = []
    total = 0
    for path_parts, record in selected:
        source_url = record["url"]
        filename = Path(urllib.parse.unquote(urllib.parse.urlparse(source_url).path)).name
        if not filename or filename in {".", ".."}:
            raise PolyHavenError("Provider returned an invalid asset filename.")
        # Preserve dependency paths where the API describes them, but never
        # allow an absolute path or parent traversal into the workspace.
        safe_parts = [re.sub(r"[^A-Za-z0-9_.-]", "_", part) for part in path_parts if part not in {"", ".", ".."}]
        if safe_parts and safe_parts[0].lower() in {"gltf", "blend", "fbx", "obj"}:
            safe_parts = safe_parts[1:]
        relative = Path(*safe_parts[:-1], filename) if safe_parts else Path(filename)
        target = (destination / relative).resolve()
        if destination not in target.parents:
            raise PolyHavenError("Provider asset path escapes the asset folder.")
        size = _download_verified(source_url, target, int(record["size"]), str(record.get("md5") or ""))
        total += size
        downloaded.append({"path": str(target.relative_to(project)).replace("\\", "/"), "bytes": size})
    manifest = {
        "schema_version": 1,
        "provider": "Poly Haven",
        "provider_asset_id": asset_id,
        "name": asset.get("name") or asset_id,
        "license": "CC0-1.0",
        "api_credit": "Powered by Poly Haven",
        "source_url": f"https://polyhaven.com/a/{asset_id}",
        "resolution": resolution,
        "files": downloaded,
        "total_bytes": total,
        "integrity": "Provider MD5 and declared file sizes verified",
    }
    manifest_path = destination / "nexora-asset-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"downloaded": True, "asset_id": asset_id, "name": manifest["name"],
            "directory": str(destination.relative_to(project)).replace("\\", "/"),
            "files": downloaded, "total_bytes": total, "license": "CC0-1.0",
            "provider": "Poly Haven", "manifest": str(manifest_path.relative_to(project)).replace("\\", "/")}
