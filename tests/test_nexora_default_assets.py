from __future__ import annotations

import json
import wave

from core.nexora_workspace.default_assets import catalog, infer_pack, install_pack


def test_catalog_exposes_offline_original_asset_packs():
    result = catalog()
    assert {item["id"] for item in result["packs"]} == {"adventure", "fantasy", "sci_fi", "modern"}
    assert all(item["offline"] and item["license"] == "CC0-1.0" for item in result["packs"])


def test_prompt_context_selects_a_relevant_visual_pack():
    assert infer_pack("A space adventure with robots on an alien planet") == "sci_fi"
    assert infer_pack("A wizard protects an enchanted castle") == "fantasy"
    assert infer_pack("A modern city street racing game") == "modern"
    assert infer_pack("A young explorer crosses a jungle") == "adventure"


def test_installs_complete_original_asset_pack(tmp_path):
    result = install_pack(tmp_path, "adventure")
    assert result["asset_count"] >= 12
    root = tmp_path / "assets" / "nexora-defaults"
    manifest = json.loads((root / "asset-pack.json").read_text(encoding="utf-8"))
    assert manifest["license"] == "CC0-1.0"
    assert (root / "characters" / "player_idle.svg").is_file()
    assert (root / "environment" / "ground_tile.svg").is_file()
    assert (root / "ui" / "button_primary.svg").is_file()
    assert (tmp_path / "scripts" / "nexora_default_assets.gd").is_file()
    with wave.open(str(root / "audio" / "jump.wav"), "rb") as sound:
        assert sound.getnframes() > 0
        assert sound.getframerate() == 22050
    with wave.open(str(root / "audio" / "background_music.wav"), "rb") as music:
        assert music.getnframes() > 22050


def test_install_is_safe_and_preserves_existing_creator_files(tmp_path):
    first = install_pack(tmp_path, "fantasy")
    custom = tmp_path / "assets" / "nexora-defaults" / "creator-note.txt"
    custom.write_text("keep me", encoding="utf-8")
    second = install_pack(tmp_path, "fantasy", overwrite=False)
    assert custom.read_text(encoding="utf-8") == "keep me"
    assert second["asset_count"] == first["asset_count"]



def test_switching_pack_requires_explicit_overwrite(tmp_path):
    install_pack(tmp_path, "adventure")
    try:
        install_pack(tmp_path, "fantasy", overwrite=False)
    except ValueError as exc:
        assert "Confirm overwrite" in str(exc)
    else:
        raise AssertionError("A pack switch must never silently replace the creator's current assets.")

    changed = install_pack(tmp_path, "fantasy", overwrite=True)
    manifest = json.loads((tmp_path / "assets" / "nexora-defaults" / "asset-pack.json").read_text(encoding="utf-8"))
    assert changed["pack"] == manifest["pack_id"] == "fantasy"
