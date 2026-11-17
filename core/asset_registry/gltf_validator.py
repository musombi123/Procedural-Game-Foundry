"""Structural glTF 2.0 / GLB validation for creator-imported assets.

This validator checks container integrity, JSON structure, references and local
resource paths. It does not replace Godot's actual importer or visual review.
"""
from __future__ import annotations

import base64
import json
import struct
from pathlib import Path
from urllib.parse import unquote


GLB_MAGIC = 0x46546C67
JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942
MAX_ASSET_BYTES = 512 * 1024 * 1024


def _resource_path(root: Path, uri: str) -> Path:
    decoded = unquote(uri)
    if decoded.startswith(("http://", "https://", "//")):
        raise ValueError("Remote resource URIs are not accepted for project assets")
    if decoded.startswith("data:"):
        header, _, payload = decoded.partition(",")
        if not payload or ";base64" not in header:
            raise ValueError("Only base64 data URIs are supported")
        base64.b64decode(payload, validate=True)
        return root
    candidate = (root / decoded).resolve()
    if root.resolve() not in candidate.parents:
        raise ValueError("Resource URI escapes the asset directory")
    if not candidate.is_file():
        raise ValueError(f"Referenced resource is missing: {uri}")
    return candidate


def _validate_document(document: dict, root: Path, binary_length: int | None) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    asset = document.get("asset")
    if not isinstance(asset, dict) or str(asset.get("version", "")) != "2.0":
        errors.append("glTF asset.version must be 2.0")

    buffers = document.get("buffers", [])
    if not isinstance(buffers, list):
        errors.append("buffers must be an array")
        buffers = []
    for index, buffer in enumerate(buffers):
        if not isinstance(buffer, dict):
            errors.append(f"buffer {index} must be an object")
            continue
        length = buffer.get("byteLength")
        if not isinstance(length, int) or length < 0:
            errors.append(f"buffer {index} has an invalid byteLength")
            continue
        uri = buffer.get("uri")
        if uri:
            try:
                resource = _resource_path(root, str(uri))
                if not str(uri).startswith("data:") and resource.stat().st_size < length:
                    errors.append(f"buffer {index} is shorter than byteLength")
            except (ValueError, OSError) as exc:
                errors.append(f"buffer {index}: {exc}")
        elif binary_length is None or binary_length < length:
            errors.append(f"buffer {index} has no sufficient embedded GLB binary chunk")

    images = document.get("images", [])
    if not isinstance(images, list):
        errors.append("images must be an array")
        images = []
    for index, image in enumerate(images):
        if not isinstance(image, dict):
            errors.append(f"image {index} must be an object")
            continue
        uri = image.get("uri")
        view = image.get("bufferView")
        if uri:
            try:
                _resource_path(root, str(uri))
            except (ValueError, OSError) as exc:
                errors.append(f"image {index}: {exc}")
        elif not isinstance(view, int):
            errors.append(f"image {index} must define uri or bufferView")

    def check_indices(collection_name: str, field: str, upper: int) -> None:
        collection = document.get(collection_name, [])
        if not isinstance(collection, list):
            errors.append(f"{collection_name} must be an array")
            return
        for index, item in enumerate(collection):
            if not isinstance(item, dict):
                errors.append(f"{collection_name}[{index}] must be an object")
                continue
            value = item.get(field)
            if value is not None and (not isinstance(value, int) or value < 0 or value >= upper):
                errors.append(f"{collection_name}[{index}].{field} references an invalid index")

    accessors = document.get("accessors", [])
    views = document.get("bufferViews", [])
    materials = document.get("materials", [])
    meshes = document.get("meshes", [])
    nodes = document.get("nodes", [])
    scenes = document.get("scenes", [])
    check_indices("accessors", "bufferView", len(views))
    check_indices("bufferViews", "buffer", len(buffers))
    check_indices("textures", "source", len(images))
    check_indices("textures", "sampler", len(document.get("samplers", [])))
    check_indices("materials", "pbrMetallicRoughness", len(materials)) if False else None

    for index, mesh in enumerate(meshes if isinstance(meshes, list) else []):
        for primitive in mesh.get("primitives", []) if isinstance(mesh, dict) else []:
            attributes = primitive.get("attributes", {})
            for semantic, accessor_index in attributes.items():
                if not isinstance(accessor_index, int) or not 0 <= accessor_index < len(accessors):
                    errors.append(f"mesh {index} attribute {semantic} references an invalid accessor")
            indices = primitive.get("indices")
            if indices is not None and (not isinstance(indices, int) or not 0 <= indices < len(accessors)):
                errors.append(f"mesh {index} references an invalid index accessor")
            material = primitive.get("material")
            if material is not None and (not isinstance(material, int) or not 0 <= material < len(materials)):
                errors.append(f"mesh {index} references an invalid material")

    for index, node in enumerate(nodes if isinstance(nodes, list) else []):
        mesh = node.get("mesh") if isinstance(node, dict) else None
        if mesh is not None and (not isinstance(mesh, int) or not 0 <= mesh < len(meshes)):
            errors.append(f"node {index} references an invalid mesh")
        children = node.get("children", []) if isinstance(node, dict) else []
        for child in children:
            if not isinstance(child, int) or not 0 <= child < len(nodes):
                errors.append(f"node {index} contains an invalid child reference")

    for index, scene in enumerate(scenes if isinstance(scenes, list) else []):
        for node in scene.get("nodes", []) if isinstance(scene, dict) else []:
            if not isinstance(node, int) or not 0 <= node < len(nodes):
                errors.append(f"scene {index} contains an invalid node reference")

    animations = document.get("animations", [])
    for index, animation in enumerate(animations if isinstance(animations, list) else []):
        for sampler in animation.get("samplers", []) if isinstance(animation, dict) else []:
            for key in ("input", "output"):
                accessor_index = sampler.get(key)
                if not isinstance(accessor_index, int) or not 0 <= accessor_index < len(accessors):
                    errors.append(f"animation {index} sampler has an invalid {key} accessor")
        for channel in animation.get("channels", []) if isinstance(animation, dict) else []:
            sampler_index = channel.get("sampler")
            if not isinstance(sampler_index, int) or not 0 <= sampler_index < len(animation.get("samplers", [])):
                errors.append(f"animation {index} channel has an invalid sampler")

    if not meshes:
        warnings.append("Asset contains no meshes")
    if not nodes:
        warnings.append("Asset contains no scene nodes")
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "stats": {
            "meshes": len(meshes) if isinstance(meshes, list) else 0,
            "nodes": len(nodes) if isinstance(nodes, list) else 0,
            "materials": len(materials) if isinstance(materials, list) else 0,
            "animations": len(animations) if isinstance(animations, list) else 0,
            "textures": len(document.get("textures", [])),
            "images": len(images),
        },
    }


def validate_gltf(path: Path) -> dict:
    path = path.resolve()
    if not path.is_file():
        return {"valid": False, "errors": ["Asset file does not exist"], "warnings": [], "stats": {}}
    if path.stat().st_size > MAX_ASSET_BYTES:
        return {"valid": False, "errors": ["Asset exceeds the 512 MiB validation limit"], "warnings": [], "stats": {}}
    suffix = path.suffix.lower()
    if suffix not in {".glb", ".gltf"}:
        return {"valid": False, "errors": ["Only .glb and .gltf assets are supported"], "warnings": [], "stats": {}}

    try:
        if suffix == ".gltf":
            document = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(document, dict):
                raise ValueError("glTF root must be a JSON object")
            return _validate_document(document, path.parent, None)

        data = path.read_bytes()
        if len(data) < 20:
            raise ValueError("GLB file is shorter than its header and JSON chunk")
        magic, version, total_length = struct.unpack_from("<III", data, 0)
        if magic != GLB_MAGIC:
            raise ValueError("Invalid GLB magic header")
        if version != 2:
            raise ValueError(f"Unsupported GLB version: {version}")
        if total_length != len(data):
            raise ValueError("GLB declared length does not match file size")
        offset = 12
        document = None
        binary_length = None
        while offset < len(data):
            if offset + 8 > len(data):
                raise ValueError("Truncated GLB chunk header")
            chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
            offset += 8
            end = offset + chunk_length
            if end > len(data):
                raise ValueError("GLB chunk exceeds declared file length")
            chunk = data[offset:end]
            if chunk_type == JSON_CHUNK:
                if document is not None:
                    raise ValueError("GLB contains multiple JSON chunks")
                document = json.loads(chunk.rstrip(b" \t\r\n\0").decode("utf-8"))
            elif chunk_type == BIN_CHUNK:
                if binary_length is not None:
                    raise ValueError("GLB contains multiple BIN chunks")
                binary_length = chunk_length
            offset = end
        if not isinstance(document, dict):
            raise ValueError("GLB is missing a valid JSON chunk")
        return _validate_document(document, path.parent, binary_length)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, struct.error, ValueError) as exc:
        return {"valid": False, "errors": [str(exc)], "warnings": [], "stats": {}}
