"""Offline, license-clean starter assets for NEXORA Godot projects.

All assets are generated deterministically from original SVG/vector geometry and
small synthesized WAV files. No remote URLs, model downloads or third-party art.
"""
from __future__ import annotations

import json
import math
import shutil
import struct
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
PACKS: dict[str, dict[str, Any]] = {
    "adventure": {"name": "Adventure", "description": "Bright exploration, forests and ruins", "sky": "#8bc9e8", "ground": "#547c43", "accent": "#f3b63f", "dark": "#263b32", "enemy": "#9b5144"},
    "fantasy": {"name": "Fantasy", "description": "Enchanted woodland, stone and magic", "sky": "#a9a0d8", "ground": "#426b52", "accent": "#e6c46b", "dark": "#302b49", "enemy": "#754c91"},
    "sci_fi": {"name": "Sci-Fi", "description": "Futuristic technology and neon interfaces", "sky": "#18334d", "ground": "#315568", "accent": "#55e0d0", "dark": "#101d32", "enemy": "#d45c75"},
    "modern": {"name": "Modern", "description": "Contemporary streets and clean interface elements", "sky": "#9bc6d8", "ground": "#64727b", "accent": "#ef9d45", "dark": "#29343d", "enemy": "#bb5151"},
}

def catalog() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "packs": [
        {"id": key, "name": value["name"], "description": value["description"],
         "asset_types": ["character", "environment", "props", "collectibles", "ui", "audio"],
         "license": "CC0-1.0 (original procedural assets)", "offline": True}
        for key, value in PACKS.items()
    ]}

def _svg(width: int, height: int, body: str) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">{body}</svg>\n'

def _write_svg(root: Path, relative: str, width: int, height: int, body: str) -> dict[str, str]:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_text(_svg(width, height, body), encoding="utf-8")
    return {"path": relative.replace("\\", "/"), "type": "image/svg+xml", "role": Path(relative).stem}

def _character(color: str, dark: str, pose: str) -> str:
    # Original, deliberately neutral adventurer silhouette; each pose is a
    # separate importable texture so creators can replace it with a real rig.
    limbs = {
        "idle": '<path d="M29 55 L22 78 L25 99 M49 55 L55 78 L52 99 M25 99 L17 104 M52 99 L61 104"/>',
        "run": '<path d="M29 55 L12 72 L5 91 M49 55 L66 66 L76 54 M25 99 L8 115 M52 99 L68 112"/>',
        "jump": '<path d="M29 55 L12 42 L4 28 M49 55 L65 42 L75 27 M25 99 L13 85 M52 99 L65 84"/>',
    }[pose]
    return f'<g stroke="{dark}" stroke-width="7" stroke-linecap="round" stroke-linejoin="round" fill="none">{limbs}</g><path d="M24 36 Q39 28 55 36 L57 67 Q40 78 22 67Z" fill="{color}" stroke="{dark}" stroke-width="3"/><circle cx="40" cy="22" r="15" fill="#f0c49b" stroke="{dark}" stroke-width="3"/><path d="M25 20 Q27 2 44 7 Q56 8 56 21Z" fill="{dark}"/><path d="M30 23h3 M46 23h3" stroke="{dark}" stroke-width="3" stroke-linecap="round"/>'

def _make_wav(path: Path, frequency: float, duration: float, kind: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    rate = 22050
    frames = int(rate * duration)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(rate)
        data = bytearray()
        for i in range(frames):
            t = i / rate
            envelope = min(1.0, i / max(1, int(rate * .02))) * max(0.0, 1.0 - t / duration)
            if kind == "noise":
                # Deterministic pseudo-noise avoids random, non-reproducible packs.
                sample = math.sin(i * 12.9898) * math.sin(i * .173)
            elif kind == "coin":
                sample = math.sin(2 * math.pi * (frequency + 500 * t) * t)
            elif kind == "music":
                sample = (
                    math.sin(2 * math.pi * 261.63 * t)
                    + 0.65 * math.sin(2 * math.pi * 329.63 * t)
                    + 0.5 * math.sin(2 * math.pi * 392.00 * t)
                    + 0.25 * math.sin(2 * math.pi * 523.25 * t)
                ) / 2.4
            else:
                sample = math.sin(2 * math.pi * frequency * t)
            data.extend(struct.pack("<h", int(max(-1, min(1, sample * envelope * .28)) * 32767)))
        output.writeframes(data)

def infer_pack(text: str) -> str:
    value = str(text or "").lower()
    if any(word in value for word in ("sci-fi", "sci fi", "space", "robot", "cyber", "alien", "futur")):
        return "sci_fi"
    if any(word in value for word in ("fantasy", "magic", "wizard", "dragon", "castle", "enchanted")):
        return "fantasy"
    if any(word in value for word in ("city", "urban", "modern", "street", "police", "racing", "school")):
        return "modern"
    return "adventure"


def install_pack(project_root: Path, pack_id: str, overwrite: bool = False) -> dict[str, Any]:
    if pack_id not in PACKS:
        raise ValueError("Unknown default asset pack.")
    root = (project_root / "assets" / "nexora-defaults").resolve()
    project = project_root.resolve()
    if project not in root.parents:
        raise ValueError("Asset destination escapes the Godot project.")
    existing_manifest = root / "asset-pack.json"
    if existing_manifest.is_file() and not overwrite:
        try:
            previous_pack = json.loads(existing_manifest.read_text(encoding="utf-8")).get("pack_id")
        except (OSError, ValueError):
            previous_pack = None
        if previous_pack and previous_pack != pack_id:
            raise ValueError("A different default pack is already installed. Confirm overwrite to replace it.")
    if root.exists() and overwrite:
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    palette = PACKS[pack_id]
    assets: list[dict[str, str]] = []
    # Character poses: idle, run and jump.
    for pose in ("idle", "run", "jump"):
        assets.append(_write_svg(root, f"characters/player_{pose}.svg", 80, 128,
                                 _character(palette["accent"], palette["dark"], pose)))
    # Reusable environment tiles and layered backdrop.
    assets.append(_write_svg(root, "environment/ground_tile.svg", 128, 64,
        f'<rect width="128" height="64" rx="8" fill="{palette["ground"]}"/><path d="M0 12 Q30 2 60 12 T128 12" fill="none" stroke="{palette["accent"]}" stroke-width="5" opacity=".65"/><path d="M18 35l8 4m30-14 8 5m35 19 8-5" stroke="{palette["dark"]}" stroke-width="4" opacity=".45"/>'))
    assets.append(_write_svg(root, "environment/sky_background.svg", 640, 360,
        f'<rect width="640" height="360" fill="{palette["sky"]}"/><circle cx="520" cy="78" r="35" fill="{palette["accent"]}" opacity=".9"/><path d="M0 260 Q120 150 250 245 T500 220 T640 245 V360 H0Z" fill="{palette["ground"]}"/><path d="M0 300 Q180 230 330 300 T640 275 V360 H0Z" fill="{palette["dark"]}" opacity=".28"/>'))
    assets.append(_write_svg(root, "environment/platform.svg", 160, 32,
        f'<rect x="2" y="5" width="156" height="25" rx="7" fill="{palette["ground"]}" stroke="{palette["dark"]}" stroke-width="4"/><path d="M8 10h144" stroke="{palette["accent"]}" stroke-width="4"/>'))
    # Props, enemy and collectible.
    assets.append(_write_svg(root, "props/crate.svg", 64, 64,
        f'<rect x="4" y="4" width="56" height="56" rx="5" fill="{palette["ground"]}" stroke="{palette["dark"]}" stroke-width="5"/><path d="M9 9L55 55M55 9L9 55" stroke="{palette["accent"]}" stroke-width="6"/>'))
    assets.append(_write_svg(root, "actors/enemy.svg", 72, 72,
        f'<path d="M12 60L16 28Q36 -2 56 28L60 60Z" fill="{palette["enemy"]}" stroke="{palette["dark"]}" stroke-width="5"/><circle cx="27" cy="34" r="5" fill="white"/><circle cx="47" cy="34" r="5" fill="white"/><path d="M27 49q10 8 20 0" stroke="{palette["dark"]}" stroke-width="4" fill="none"/>'))
    assets.append(_write_svg(root, "collectibles/gem.svg", 48, 56,
        f'<path d="M24 2L45 20L24 54L3 20Z" fill="{palette["accent"]}" stroke="{palette["dark"]}" stroke-width="4"/><path d="M3 20h42M24 2l-6 18 6 34 7-34Z" fill="white" opacity=".25"/>'))
    # UI components are SVG textures so no external font or icon dependency.
    assets.append(_write_svg(root, "ui/heart.svg", 40, 36,
        '<path d="M20 34S2 22 2 12C2 -1 17 -2 20 9 25 -2 39 -1 38 12 38 22 20 34 20 34Z" fill="#e85d75" stroke="#66283b" stroke-width="3"/>'))
    assets.append(_write_svg(root, "ui/panel.svg", 320, 100,
        f'<rect x="3" y="3" width="314" height="94" rx="16" fill="{palette["dark"]}" fill-opacity=".92" stroke="{palette["accent"]}" stroke-width="6"/>'))
    assets.append(_write_svg(root, "ui/button_primary.svg", 240, 72,
        f'<rect x="3" y="3" width="234" height="66" rx="18" fill="{palette["accent"]}" stroke="{palette["dark"]}" stroke-width="6"/>'))
    assets.append(_write_svg(root, "ui/button_secondary.svg", 240, 72,
        f'<rect x="3" y="3" width="234" height="66" rx="18" fill="{palette["dark"]}" stroke="{palette["accent"]}" stroke-width="5"/>'))
    assets.append(_write_svg(root, "ui/icon_play.svg", 64, 64,
        f'<circle cx="32" cy="32" r="29" fill="{palette["dark"]}" stroke="{palette["accent"]}" stroke-width="4"/><path d="M25 17L49 32L25 47Z" fill="{palette["accent"]}"/>'))
    assets.append(_write_svg(root, "ui/icon_pause.svg", 64, 64,
        f'<circle cx="32" cy="32" r="29" fill="{palette["dark"]}" stroke="{palette["accent"]}" stroke-width="4"/><path d="M21 18h8v28h-8zm14 0h8v28h-8z" fill="{palette["accent"]}"/>'))
    # Short, original synthesized cues: jump, collect, hit and loopable ambience.
    audio = []
    for name, freq, duration, kind in (
        ("jump", 520, .18, "tone"), ("collect", 880, .24, "coin"),
        ("hit", 130, .20, "noise"), ("ambience", 110, 2.0, "tone"),
        ("background_music", 262, 8.0, "music"),
    ):
        rel = f"audio/{name}.wav"
        _make_wav(root / rel, freq, duration, kind)
        audio.append({"path": rel, "type": "audio/wav", "role": name})
    assets.extend(audio)
    manifest = {
        "schema_version": SCHEMA_VERSION, "pack_id": pack_id, "pack_name": palette["name"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "NEXORA deterministic procedural starter assets",
        "license": "CC0-1.0", "provenance": "Original vector geometry and synthesized audio; no third-party source files.",
        "engine": "Godot 4", "assets": assets,
        "notes": ["Textures are editable SVG source files.", "Character poses are starter sprites, not skeletal rigs.",
                  "Replace or extend these assets freely; generated files are contained in assets/nexora-defaults."]
    }
    manifest_path = root / "asset-pack.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    helper = project_root / "scripts" / "nexora_default_assets.gd"
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper_source = """extends RefCounted
class_name NexoraDefaultAssets

const ROOT := "res://assets/nexora-defaults/"

static func player_texture(pose: String = "idle") -> Texture2D:
    var safe_pose := pose if pose in ["idle", "run", "jump"] else "idle"
    return load(ROOT + "characters/player_" + safe_pose + ".svg") as Texture2D

static func environment_texture(name: String) -> Texture2D:
    var safe_name := name if name in ["ground_tile", "sky_background", "platform"] else "ground_tile"
    return load(ROOT + "environment/" + safe_name + ".svg") as Texture2D

static func ui_texture(name: String) -> Texture2D:
    var safe_name := name if name in ["heart", "panel", "button_primary", "button_secondary", "icon_play", "icon_pause"] else "panel"
    return load(ROOT + "ui/" + safe_name + ".svg") as Texture2D

static func play_audio(player: AudioStreamPlayer, cue: String) -> void:
    if cue not in ["jump", "collect", "hit", "ambience", "background_music"]:
        return
    player.stream = load(ROOT + "audio/" + cue + ".wav") as AudioStream
    player.play()
"""
    if not helper.exists():
        helper.write_text(helper_source, encoding="utf-8")
    return {"installed": True, "pack": pack_id, "asset_count": len(assets),
            "directory": "assets/nexora-defaults", "manifest": "assets/nexora-defaults/asset-pack.json",
            "assets": assets, "license": "CC0-1.0", "offline": True}
