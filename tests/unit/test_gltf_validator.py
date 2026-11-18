import json
import struct

from core.asset_registry.gltf_validator import JSON_CHUNK, GLB_MAGIC, validate_gltf


def _write_glb(path, document):
    encoded = json.dumps(document, separators=(",", ":")).encode("utf-8")
    encoded += b" " * ((4 - len(encoded) % 4) % 4)
    chunk = struct.pack("<II", len(encoded), JSON_CHUNK) + encoded
    path.write_bytes(struct.pack("<III", GLB_MAGIC, 2, 12 + len(chunk)) + chunk)


def test_valid_glb_reports_scene_statistics(tmp_path):
    asset = tmp_path / "world.glb"
    _write_glb(asset, {
        "asset": {"version": "2.0", "generator": "Blender"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "WorldRoot"}],
        "meshes": [],
        "materials": [],
        "animations": [],
    })
    result = validate_gltf(asset)
    assert result["valid"] is True
    assert result["stats"]["nodes"] == 1


def test_glb_rejects_invalid_header_and_length(tmp_path):
    asset = tmp_path / "broken.glb"
    asset.write_bytes(b"not-a-glb")
    result = validate_gltf(asset)
    assert result["valid"] is False
    assert "shorter than" in result["errors"][0]


def test_gltf_checks_external_buffer_and_mesh_references(tmp_path):
    (tmp_path / "mesh.bin").write_bytes(b"\x00" * 12)
    asset = tmp_path / "mesh.gltf"
    asset.write_text(json.dumps({
        "asset": {"version": "2.0"},
        "buffers": [{"uri": "mesh.bin", "byteLength": 12}],
        "bufferViews": [{"buffer": 0, "byteLength": 12}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": 1, "type": "VEC3"}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "nodes": [{"mesh": 0}],
        "scenes": [{"nodes": [0]}],
    }), encoding="utf-8")
    result = validate_gltf(asset)
    assert result["valid"] is True
    assert result["stats"]["meshes"] == 1


def test_gltf_rejects_path_traversal_and_bad_references(tmp_path):
    asset = tmp_path / "unsafe.gltf"
    asset.write_text(json.dumps({
        "asset": {"version": "2.0"},
        "buffers": [{"uri": "../secret.bin", "byteLength": 4}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 99}}]}],
    }), encoding="utf-8")
    result = validate_gltf(asset)
    assert result["valid"] is False
    assert any("escapes" in error for error in result["errors"])
    assert any("invalid accessor" in error for error in result["errors"])
