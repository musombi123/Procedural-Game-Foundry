from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from core.nexora_workspace import polyhaven_assets as assets


def test_search_returns_only_real_3d_models(monkeypatch):
    monkeypatch.setattr(assets, "_request_json", lambda url: {
        "dirty_football": {"type": 2, "name": "Dirty Football", "category": "Sports", "tags": ["ball"], "thumbnail_url": "https://cdn.polyhaven.com/thumb.png", "polycount": 37486},
        "concrete_floor_01": {"type": 1, "name": "Concrete Floor", "tags": ["floor"]},
        "sunset": {"type": 0, "name": "Sunset", "tags": ["sky"]},
    })
    result = assets.search_models("football")
    assert result["count"] == 1
    assert result["results"][0]["id"] == "dirty_football"
    assert result["results"][0]["license"] == "CC0-1.0"


def test_direct_download_verifies_provider_file_and_writes_project_manifest(tmp_path, monkeypatch):
    payloads = {
        f"{assets.API_ROOT}/assets?t=models": {
            "dirty_football": {"type": 2, "name": "Dirty Football", "category": "Sports"}
        },
        f"{assets.API_ROOT}/files/dirty_football": {
            "gltf": {
                "2k": {
                    "glb": {
                        "url": "https://dl.polyhaven.org/file/ph-assets/Models/glb/2k/dirty_football.glb",
                        "size": 12,
                        "md5": hashlib.md5(b"real-model!!").hexdigest(),
                    }
                }
            }
        },
    }
    monkeypatch.setattr(assets, "_request_json", lambda url: payloads[url])

    def fake_download(url, target, expected_size, expected_md5):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"real-model!!")
        assert len(target.read_bytes()) == expected_size
        assert hashlib.md5(target.read_bytes()).hexdigest() == expected_md5
        return expected_size

    monkeypatch.setattr(assets, "_download_verified", fake_download)
    result = assets.download_model(tmp_path, "dirty_football", "2k")
    model = tmp_path / "assets/3d/polyhaven/dirty_football/dirty_football.glb"
    manifest = json.loads((model.parent / "nexora-asset-manifest.json").read_text())
    registry = json.loads((tmp_path / "assets" / "assets.json").read_text())
    assert result["downloaded"] is True
    assert model.read_bytes() == b"real-model!!"
    assert manifest["provider"] == "Poly Haven"
    assert manifest["license"] == "CC0-1.0"
    assert manifest["integrity"].startswith("Provider MD5")
    assert registry["assets"][0]["asset_id"] == "polyhaven_dirty_football"
    assert registry["assets"][0]["path"] == "3d/polyhaven/dirty_football/dirty_football.glb"


def test_rejects_invalid_asset_ids_and_resolution(tmp_path):
    with pytest.raises(assets.PolyHavenError):
        assets.download_model(tmp_path, "../outside", "2k")
    with pytest.raises(assets.PolyHavenError):
        assets.download_model(tmp_path, "dirty_football", "8k")


def test_rejects_untrusted_provider_download_hosts():
    with pytest.raises(assets.PolyHavenError):
        assets._download_verified("https://example.com/model.glb", Path("model.glb"), 12, "")



def test_refuses_download_when_provider_checksum_is_missing(tmp_path):
    with pytest.raises(assets.PolyHavenError, match="valid MD5 checksum"):
        assets._download_verified(
            "https://dl.polyhaven.org/file/ph-assets/model.glb",
            tmp_path / "model.glb",
            12,
            "",
        )



def test_auto_install_from_prompt_selects_and_registers_relevant_models(tmp_path, monkeypatch):
    calls = []

    def fake_search(query, limit=12):
        calls.append(query)
        return {"results": [{
            "id": f"{query}_model",
            "name": f"{query.title()} Model",
            "description": "A real 3D model",
            "category": "Props",
            "tags": [query],
        }]}

    monkeypatch.setattr(assets, "search_models", fake_search)
    monkeypatch.setattr(assets, "_request_json", lambda url: {
        "gltf": {"1k": {"glb": {
            "url": "https://dl.polyhaven.org/file/ph-assets/Models/model.glb",
            "size": 10,
            "md5": "a" * 32,
        }}}
    })
    monkeypatch.setattr(assets, "download_model", lambda root, asset_id, resolution: {
        "downloaded": True, "asset_id": asset_id,
        "asset_registry_id": f"polyhaven_{asset_id}",
        "name": asset_id.replace("_", " ").title(),
        "model_path": f"3d/polyhaven/{asset_id}/{asset_id}.glb",
        "total_bytes": 10,
    })

    result = assets.auto_install_from_prompt(tmp_path, "A jungle survival adventure", "1k", 3)
    assert result["resolution"] == "1k"
    assert 1 <= len(result["assets"]) <= 3
    assert result["assets"][0]["asset_registry_id"].startswith("polyhaven_")
    assert calls[0] == "tree"


def test_auto_3d_asset_discovery_fails_soft_when_provider_is_offline(tmp_path, monkeypatch):
    def unavailable(*args, **kwargs):
        raise assets.PolyHavenError("provider offline")

    monkeypatch.setattr(assets, "search_models", unavailable)
    result = assets.auto_install_from_prompt(tmp_path, "A jungle game")
    assert result["assets"] == []
    assert result["warnings"]
