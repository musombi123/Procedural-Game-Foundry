"""Authenticated NEXORA workspace API adapters over the Foundry project engine.

The workspace document remains the editor-facing representation; the project engine's
validated WorldDocument is synchronised before scene generation and export.
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import math
import shutil
import struct
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response

from core.asset_registry.gltf_validator import MAX_ASSET_BYTES, validate_gltf
from core.asset_registry.registry import AssetRegistry
from core.build_engine.godot_cli import executable as godot_executable
from core.game_assembler.godot import assemble_godot_project
from core.project_engine.models import ProjectCreate, SceneObject, WorldDocument
from core.validation.validator import validate_project

_WRITE_LOCK = RLock()
TEMPLATES = [
    {"id":"sci_fi_crate","name":"Neon Cargo Crate","category":"Props","kind":"crate","description":"Modular industrial cargo container","default_scale":1.0},
    {"id":"signal_beacon","name":"Signal Beacon","category":"Props","kind":"beacon","description":"Glowing navigation and objective marker","default_scale":1.0},
    {"id":"alien_tree","name":"Alien Tree","category":"Environments","kind":"tree","description":"Procedural alien vegetation","default_scale":1.0},
    {"id":"rock_formation","name":"Rock Formation","category":"Environments","kind":"rock","description":"Natural terrain landmark","default_scale":1.0},
    {"id":"sci_fi_outpost","name":"Sci-Fi Outpost","category":"Environments","kind":"outpost","description":"Modular player shelter / mission site","default_scale":1.0},
    {"id":"tactical_android","name":"Tactical Android","category":"Characters","kind":"character","description":"Original low-poly humanoid character blockout","default_scale":1.0},
    {"id":"scout_drone","name":"Scout Drone","category":"Props","kind":"drone","description":"Compact reconnaissance drone","default_scale":1.0},
    {"id":"heavy_door","name":"Sci-Fi Heavy Door","category":"Props","kind":"door","description":"Industrial sliding bulkhead door","default_scale":1.0},
]
TEMPLATE_BY_ID = {item["id"]: item for item in TEMPLATES}

def _build_template_glb(template_id: str) -> bytes:
    """Return a small, original, procedural GLB preview for a built-in studio template."""
    if template_id not in TEMPLATE_BY_ID:
        raise HTTPException(404, "3D template not found.")
    parts: list[dict] = []

    def box(center, size, color):
        cx,cy,cz=center; sx,sy,sz=(value/2 for value in size)
        faces=[
            ((0,0,1),[(-sx,-sy,sz),(sx,-sy,sz),(sx,sy,sz),(-sx,sy,sz)]),
            ((0,0,-1),[(sx,-sy,-sz),(-sx,-sy,-sz),(-sx,sy,-sz),(sx,sy,-sz)]),
            ((1,0,0),[(sx,-sy,sz),(sx,-sy,-sz),(sx,sy,-sz),(sx,sy,sz)]),
            ((-1,0,0),[(-sx,-sy,-sz),(-sx,-sy,sz),(-sx,sy,sz),(-sx,sy,-sz)]),
            ((0,1,0),[(-sx,sy,sz),(sx,sy,sz),(sx,sy,-sz),(-sx,sy,-sz)]),
            ((0,-1,0),[(-sx,-sy,-sz),(sx,-sy,-sz),(sx,-sy,sz),(-sx,-sy,sz)]),
        ]
        vertices=[]; normals=[]; indices=[]
        for normal,face in faces:
            base=len(vertices)//3
            for x,y,z in face:
                vertices.extend([x+cx,y+cy,z+cz]); normals.extend(normal)
            indices.extend([base,base+1,base+2,base,base+2,base+3])
        parts.append({"positions":vertices,"normals":normals,"indices":indices,"color":color})

    def cylinder(center, radius, height, color, segments=24):
        cx,cy,cz=center; vertices=[]; normals=[]; indices=[]
        for y,ny in [(-height/2,0),(height/2,0)]:
            for i in range(segments):
                angle=2*math.pi*i/segments
                nx,nz=math.cos(angle),math.sin(angle)
                vertices.extend([cx+radius*nx,cy+y,cz+radius*nz]); normals.extend([nx,ny,nz])
        for i in range(segments):
            n=(i+1)%segments
            indices.extend([i,n,segments+n,i,segments+n,segments+i])
        for cap_y, normal_y in [(-height/2,-1),(height/2,1)]:
            center_index=len(vertices)//3
            vertices.extend([cx,cy+cap_y,cz]); normals.extend([0,normal_y,0])
            ring_start=len(vertices)//3
            for i in range(segments):
                angle=2*math.pi*i/segments
                vertices.extend([cx+radius*math.cos(angle),cy+cap_y,cz+radius*math.sin(angle)])
                normals.extend([0,normal_y,0])
            for i in range(segments):
                n=(i+1)%segments
                if normal_y>0: indices.extend([center_index,ring_start+i,ring_start+n])
                else: indices.extend([center_index,ring_start+n,ring_start+i])
        parts.append({"positions":vertices,"normals":normals,"indices":indices,"color":color})

    def sphere(center, radius, color, rings=12, segments=20):
        cx,cy,cz=center; vertices=[]; normals=[]; indices=[]
        for r in range(rings+1):
            phi=math.pi*r/rings
            for i in range(segments+1):
                theta=2*math.pi*i/segments
                nx=math.sin(phi)*math.cos(theta); ny=math.cos(phi); nz=math.sin(phi)*math.sin(theta)
                vertices.extend([cx+radius*nx,cy+radius*ny,cz+radius*nz]); normals.extend([nx,ny,nz])
        for r in range(rings):
            for i in range(segments):
                a=r*(segments+1)+i; b=a+segments+1
                indices.extend([a,b,a+1,a+1,b,b+1])
        parts.append({"positions":vertices,"normals":normals,"indices":indices,"color":color})

    if template_id=="sci_fi_crate":
        box((0,0,0),(2.2,1.8,2.2),"#667d8e")
        box((0,0.93,0),(2.28,0.12,2.28),"#d19a4d")
        for x in (-0.84,0.84):
            box((x,0,-1.12),(0.16,1.65,0.12),"#e1bc78")
            box((x,0,1.12),(0.16,1.65,0.12),"#e1bc78")
    elif template_id=="signal_beacon":
        cylinder((0,0.9,0),0.5,1.8,"#637d8d")
        cylinder((0,1.9,0),0.27,0.32,"#c4a45a")
        sphere((0,2.28,0),0.38,"#49d9ef")
    elif template_id=="alien_tree":
        cylinder((0,1.1,0),0.22,2.2,"#795b42")
        sphere((0,2.65,0),0.9,"#4d967a")
        sphere((0.55,2.35,0.15),0.55,"#6bad83")
    elif template_id=="rock_formation":
        sphere((0,0.65,0),0.92,"#7e858b")
        sphere((0.65,0.48,0.25),0.55,"#999b98")
        sphere((-0.48,0.4,-0.2),0.48,"#656f79")
    elif template_id=="tactical_android":
        # Static original character blockout; not a rigged or animated character.
        box((0,1.45,0),(0.82,0.92,0.42),"#b58a43")
        sphere((0,2.2,0),0.38,"#a9b7bd")
        box((0,2.2,0.34),(0.42,0.09,0.08),"#45d8ed")
        for x in (-0.58,0.58):
            cylinder((x,1.35,0),0.14,0.92,"#667b8a")
            sphere((x,0.91,0),0.16,"#d2a45c")
        for x in (-0.23,0.23):
            box((x,0.48,0),(0.2,0.78,0.24),"#596f7c")
            box((x,0.08,0.12),(0.3,0.16,0.48),"#b58a43")
    elif template_id=="scout_drone":
        box((0,0,0),(1.0,0.28,0.72),"#647d8c")
        sphere((0,0.12,0.42),0.16,"#48d9ee")
        for x in (-0.72,0.72):
            for z in (-0.58,0.58):
                box((x*0.65,0,z*0.65),(0.7,0.1,0.1),"#b78e4c")
                cylinder((x,0.08,z),0.24,0.08,"#a9b7bd")
    elif template_id=="heavy_door":
        box((0,1.5,0),(2.8,3.0,0.28),"#536b7a")
        box((0,1.5,0.17),(2.45,2.68,0.08),"#243b49")
        for x in (-1.05,1.05):
            box((x,1.5,0.24),(0.12,2.35,0.1),"#c39b55")
        box((0,1.5,0.28),(0.16,0.35,0.1),"#49d9ef")
    else:
        box((0,1.0,0),(5.4,2.0,4.4),"#596f7c")
        box((0,2.12,0),(5.8,0.24,4.8),"#c39a5f")
        box((0,0.5,2.25),(1.8,1.0,0.15),"#2f4858")
        for x in (-2.1,2.1):
            box((x,1.6,-1.8),(0.28,3.2,0.28),"#8fb6bc")

    binary=bytearray(); buffer_views=[]; accessors=[]; meshes=[]; nodes=[]; materials=[]
    for index,part in enumerate(parts):
        while len(binary)%4: binary.append(0)
        pos_offset=len(binary); pos_data=struct.pack("<"+"f"*len(part["positions"]),*part["positions"]); binary.extend(pos_data)
        pos_view=len(buffer_views); buffer_views.append({"buffer":0,"byteOffset":pos_offset,"byteLength":len(pos_data),"target":34962})
        positions=list(zip(*(iter(part["positions"]),)*3))
        min_pos=[min(vertex[axis] for vertex in positions) for axis in range(3)]
        max_pos=[max(vertex[axis] for vertex in positions) for axis in range(3)]
        pos_accessor=len(accessors); accessors.append({"bufferView":pos_view,"componentType":5126,"count":len(positions),"type":"VEC3","min":min_pos,"max":max_pos})
        while len(binary)%4: binary.append(0)
        normal_offset=len(binary); normal_data=struct.pack("<"+"f"*len(part["normals"]),*part["normals"]); binary.extend(normal_data)
        normal_view=len(buffer_views); buffer_views.append({"buffer":0,"byteOffset":normal_offset,"byteLength":len(normal_data),"target":34962})
        normal_accessor=len(accessors); accessors.append({"bufferView":normal_view,"componentType":5126,"count":len(part["normals"])//3,"type":"VEC3"})
        while len(binary)%4: binary.append(0)
        index_offset=len(binary); index_data=struct.pack("<"+"I"*len(part["indices"]),*part["indices"]); binary.extend(index_data)
        index_view=len(buffer_views); buffer_views.append({"buffer":0,"byteOffset":index_offset,"byteLength":len(index_data),"target":34963})
        index_accessor=len(accessors); accessors.append({"bufferView":index_view,"componentType":5125,"count":len(part["indices"]),"type":"SCALAR"})
        color=part["color"]
        rgb=[int(color[i:i+2],16)/255 for i in (1,3,5)]
        materials.append({"name":f"TemplateMaterial{index}","pbrMetallicRoughness":{"baseColorFactor":[*rgb,1],"metallicFactor":0.28,"roughnessFactor":0.58}})
        meshes.append({"name":f"TemplateMesh{index}","primitives":[{"attributes":{"POSITION":pos_accessor,"NORMAL":normal_accessor},"indices":index_accessor,"material":index}]})
        nodes.append({"name":f"TemplatePart{index}","mesh":index})
    document={
        "asset":{"version":"2.0","generator":"NEXORA Procedural Template Foundry"},
        "scene":0,"scenes":[{"nodes":list(range(len(nodes)))}],"nodes":nodes,
        "meshes":meshes,"materials":materials,"accessors":accessors,
        "bufferViews":buffer_views,"buffers":[{"byteLength":len(binary)}],
    }
    json_chunk=json.dumps(document,separators=(",",":")).encode("utf-8")
    json_chunk+=b" " *((4-len(json_chunk)%4)%4)
    while len(binary)%4: binary.append(0)
    total=12+8+len(json_chunk)+8+len(binary)
    return struct.pack("<III",0x46546C67,2,total)+struct.pack("<II",len(json_chunk),0x4E4F534A)+json_chunk+struct.pack("<II",len(binary),0x004E4942)+bytes(binary)
EXPORT_TARGETS = {
    "desktop": [("Windows Desktop", "windows", ".exe")],
    "windows": [("Windows Desktop", "windows", ".exe")],
    "linux": [("Linux/X11", "linux", ".x86_64")],
    "web": [("Web", "web", ".zip")],
    "android": [("Android", "android", ".apk")],
    "desktop_android": [("Windows Desktop", "windows", ".exe"), ("Android", "android", ".apk")],
}

def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()

def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(value))[:64] or uuid4().hex[:12]

def _state_path(folder: Path) -> Path:
    return folder / "nexora_workspace.json"

def _owner_path(folder: Path) -> Path:
    return folder / "nexora_owner.json"

def _owner_id(request: Request) -> str:
    value = getattr(request.state, "nexora_user_id", None)
    if not value:
        raise HTTPException(401, "A verified RevelaCode session is required.")
    return str(value)

def _assert_owner(folder: Path, request: Request) -> str:
    owner = _owner_id(request)
    marker = _owner_path(folder)
    if marker.is_file():
        try:
            recorded = json.loads(marker.read_text(encoding="utf-8")).get("user_id")
        except (OSError, ValueError):
            raise HTTPException(500, "NEXORA project ownership record is unreadable.")
        if str(recorded) != owner:
            raise HTTPException(404, "Project not found.")
    elif os.environ.get("NEXORA_AUTH_REQUIRED", "").lower() in {"1", "true", "yes"}:
        raise HTTPException(403, "This legacy project has no verified owner record. Ask the NEXORA administrator to migrate it.")
    else:
        marker.write_text(json.dumps({"user_id": owner, "created_at": _utc()}, indent=2), encoding="utf-8")
    return owner

def _load_state(folder: Path, definition: Any) -> dict:
    path = _state_path(folder)
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise HTTPException(500, "NEXORA project workspace document is unreadable.")
    project = definition.project
    return {
        "id": definition.id, "name": project.name, "description": project.description,
        "schemaVersion": 1, "engine": "Godot 4",
        "settings": {"target":"Desktop","orientation":"Landscape","renderPipeline":"Forward+"},
        "scene": {"id": uuid4().hex, "name":"Main Scene", "objects":[
            {"id":"world_root","name":"World","type":"Node3D","position":[0,0,0],"rotation":[0,0,0],"scale":[1,1,1],"visible":True},
            {"id":"player_start","name":"Player Start","type":"Marker3D","position":[0,1,4],"rotation":[0,0,0],"scale":[1,1,1],"visible":True},
        ]},
        "assets": [], "gameplay":{"enemies":[],"mechanics":[],"objectives":[]},
        "timeline":{"duration_seconds":330,"playhead_seconds":0,"tracks":[]},
        "createdAt": definition.created_at, "updatedAt": definition.created_at,
        "version": 1,
    }

def _write_state(folder: Path, state: dict) -> dict:
    with _WRITE_LOCK:
        previous = {}
        path = _state_path(folder)
        if path.is_file():
            try: previous = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError): previous = {}
        state = dict(state)
        state["id"] = str(state.get("id") or folder.name)
        state["createdAt"] = previous.get("createdAt") or state.get("createdAt") or _utc()
        state["updatedAt"] = _utc()
        state["version"] = int(previous.get("version", state.get("version", 0))) + 1
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
        temporary.replace(path)
        return state

def _row(folder: Path, definition: Any) -> dict:
    state = _load_state(folder, definition)
    return {
        "id": definition.id, "name": state.get("name") or definition.project.name,
        "description": state.get("description") or "",
        "document": {key:value for key,value in state.items() if key not in {"version"}},
        "version": int(state.get("version", 1)),
        "created_at": state.get("createdAt"), "updated_at": state.get("updatedAt"),
    }

def _sync_editor_scene_to_world(folder: Path, definition: Any, state: dict) -> WorldDocument:
    existing = folder / "world.json"
    if existing.is_file():
        try: current = WorldDocument.model_validate_json(existing.read_text(encoding="utf-8"))
        except Exception: current = WorldDocument(seed=definition.project.seed, world=definition.world)
    else:
        current = WorldDocument(seed=definition.project.seed, world=definition.world)
    objects = []
    for item in (state.get("scene") or {}).get("objects", []):
        if not isinstance(item, dict) or item.get("visible") is False:
            continue
        node_type = str(item.get("type") or "")
        if node_type in {"Node3D","Marker3D","DirectionalLight3D","Camera3D","WorldEnvironment"}:
            continue
        position = item.get("position") if isinstance(item.get("position"), list) else [0,0,0]
        rotation = item.get("rotation") if isinstance(item.get("rotation"), list) else [0,0,0]
        scale = item.get("scale") if isinstance(item.get("scale"), list) else [1,1,1]
        asset_id = item.get("asset_id")
        template_id = item.get("template_id")
        template = TEMPLATE_BY_ID.get(str(template_id))
        kind = "custom" if asset_id else (template or {}).get("kind","crate")
        try:
            objects.append(SceneObject(
                id=_safe_id(item.get("id") or uuid4().hex),
                name=str(item.get("name") or "Scene Object")[:80],
                kind=kind,
                x=max(-512,min(512,float(position[0]))),
                y=max(-100,min(100,float(position[1]))),
                z=max(-512,min(512,float(position[2]))),
                rotation=max(-360,min(360,float(rotation[1] if len(rotation)>1 else rotation[0]))),
                scale=max(0.25,min(4,float(sum(float(v) for v in scale)/3))),
                color="#8ba7c7",
                model_asset_id=str(asset_id) if asset_id else None,
            ))
        except (ValueError, TypeError, IndexError):
            raise HTTPException(422, f"Invalid transform for scene object {item.get('name') or item.get('id')}.")
    result = WorldDocument(
        seed=current.seed, world=current.world, objects=objects,
        terrain_edits=current.terrain_edits, sun_angle=current.sun_angle,
        fog=current.fog, water_level=current.water_level,
    )
    folder.joinpath("world.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return result

def _asset_rows(folder: Path) -> list[dict]:
    records = AssetRegistry(folder / "assets").list()
    output = []
    for item in records:
        path = Path(item["path"]).name
        file_path = (folder / "assets" / path).resolve()
        if not file_path.is_file():
            continue
        output.append({
            "id": item["asset_id"], "filename": path,
            "content_type": mimetypes.guess_type(path)[0] or "application/octet-stream",
            "size": file_path.stat().st_size, "created_at": datetime.fromtimestamp(file_path.stat().st_mtime, timezone.utc).isoformat(),
            "status": "ready" if item.get("metadata",{}).get("validation",{}).get("valid", True) else "failed",
            "kind": item.get("kind"), "license": item.get("license"),
            "sha256": item.get("checksum"), "metadata": item.get("metadata",{}),
        })
    return output

def _write_export_presets(game: Path, targets: list[tuple[str,str,str]], android: dict | None = None) -> None:
    sections = []
    android = android or {}
    for index, (preset, platform, suffix) in enumerate(targets):
        out_dir = game.parent / "artifacts" / platform
        out_dir.mkdir(parents=True, exist_ok=True)
        extension = "index.html" if platform == "web" else f"{game.parent.name}{suffix}"
        export_path = out_dir / extension
        lines = [
            f"[preset.{index}]", f'name="{preset}"', f'platform="{platform_label(platform)}"',
            "runnable=true", "dedicated_server=false", 'custom_features=""',
            'export_filter="all_resources"', 'include_filter=""', 'exclude_filter=""',
            f'export_path="{export_path.as_posix()}"', 'encryption_include_filters=""',
            'encryption_exclude_filters=""', "encrypt_pck=false", "encrypt_directory=false",
        ]
        options = {}
        if platform == "windows":
            options = {"custom_template/debug":"","custom_template/release":"","debug/export_console_wrapper":"1","binary_format/embed_pck":"true"}
        elif platform == "linux":
            options = {"custom_template/debug":"","custom_template/release":"","binary_format/embed_pck":"true"}
        elif platform == "web":
            options = {"variant/extensions_support":"false","vram_texture_compression/for_desktop":"true"}
        elif platform == "android":
            package_id = str(android.get("package_id") or "com.nexora.game").strip().lower()
            if not re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){1,}", package_id):
                raise RuntimeError("Android package ID must use reverse-DNS format, for example com.studio.mygame.")
            artifact_format = str(android.get("artifact_format") or "apk").lower()
            build_type = str(android.get("build_type") or "debug").lower()
            if artifact_format not in {"apk", "aab"}:
                raise RuntimeError("Android export supports APK or AAB packages.")
            if artifact_format == "aab" and build_type != "release":
                raise RuntimeError("Android App Bundles (AAB) must be built as a release package.")
            options = {
                "custom_template/debug":"", "custom_template/release":"",
                "package/unique_name":package_id,
                "package/name":str(android.get("app_name") or "NEXORA Game")[:48],
                "version/code":str(max(1,int(android.get("version_code") or 1))),
                "version/name":str(android.get("version_name") or "1.0.0")[:32],
                "architectures/arm64-v8a":"true", "architectures/armeabi-v7a":"true",
                "architectures/x86":"false", "architectures/x86_64":"false",
                "gradle_build/use_gradle_build": artifact_format == "aab",
                "permissions/internet": bool(android.get("internet_permission", True)),
                "permissions/camera": bool(android.get("camera_permission", False)),
                "permissions/record_audio": bool(android.get("microphone_permission", False)),
                "screen/support_small": True, "screen/support_normal": True,
                "screen/support_large": True, "screen/support_xlarge": True,
            }
            if artifact_format == "aab":
                options["gradle_build/export_format"] = 1
            icon_id = android.get("icon_asset_id")
            if icon_id:
                icon = next((item for item in AssetRegistry(game.parent / "assets").list() if item.get("asset_id") == icon_id), None)
                if not icon:
                    raise RuntimeError("The selected Android launcher icon is not in this project's asset library.")
                icon_path = Path(icon.get("path", ""))
                if icon_path.suffix.lower() != ".png":
                    raise RuntimeError("The Android launcher icon must be a PNG image.")
                options["launcher_icons/main_192x192"] = "res://assets/" + icon_path.as_posix()
        sections.extend(lines)
        if options:
            sections.append("")
            sections.append(f"[preset.{index}.options]")
            for key, value in options.items():
                if isinstance(value, bool):
                    serialized = "true" if value else "false"
                elif isinstance(value, int):
                    serialized = str(value)
                else:
                    serialized = json.dumps(str(value))
                sections.append(f"{key}={serialized}")
        sections.append("")
    (game / "export_presets.cfg").write_text("\n".join(sections), encoding="utf-8")


def _apply_android_orientation(game: Path, android: dict | None) -> None:
    if not android:
        return
    orientation_values = {"landscape":0, "portrait":1, "sensor":6}
    orientation = str(android.get("orientation") or "landscape").lower()
    if orientation not in orientation_values:
        raise RuntimeError("Android orientation must be landscape, portrait or sensor.")
    project_file = game / "project.godot"
    text = project_file.read_text(encoding="utf-8")
    text = re.sub(r"(?m)^window/handheld/orientation=.*\\n?", "", text)
    if orientation == "portrait":
        text = re.sub(r"(?m)^window/size/viewport_width=.*$", "window/size/viewport_width=720", text)
        text = re.sub(r"(?m)^window/size/viewport_height=.*$", "window/size/viewport_height=1280", text)
    display_section = re.search(r"(?m)^\\[display\\]\\s*$", text)
    if display_section:
        insert_at = display_section.end()
        text = text[:insert_at] + f"\\nwindow/handheld/orientation={orientation_values[orientation]}" + text[insert_at:]
    else:
        text += f"\\n[display]\\nwindow/handheld/orientation={orientation_values[orientation]}\\n"
    project_file.write_text(text, encoding="utf-8")

def platform_label(platform: str) -> str:
    return {"windows":"Windows Desktop","linux":"Linux/X11","web":"Web","android":"Android"}[platform]

def _run_workspace_job(job_id: str, project_id: str, kind: str, target: str, android: dict | None, manager: Any, jobs: Any) -> None:
    try:
        jobs.update(job_id, state=__import__("core.orchestration.jobs",fromlist=["JobState"]).JobState.RUNNING, progress=5, message="Preparing NEXORA production project")
        definition = manager.load(project_id)
        folder = manager.path_for(project_id)
        state = _load_state(folder, definition)
        world = _sync_editor_scene_to_world(folder, definition, state)
        jobs.update(job_id, progress=20, message="Synchronised scene, 3D assets and world data")
        game = assemble_godot_project(definition, folder / "game", world.model_dump(mode="json"))
        report = validate_project(folder)
        if not report.get("valid"):
            raise RuntimeError("Generated Godot project validation failed: " + "; ".join(report.get("errors",[])))
        if kind == "scene.generate":
            jobs.update(job_id, state=__import__("core.orchestration.jobs",fromlist=["JobState"]).JobState.COMPLETED, progress=100, message="Godot scene generated and structurally validated", error=None)
            return
        exe = godot_executable()
        if not exe:
            raise RuntimeError("Godot 4 is not installed on this worker. Install Godot 4 and export templates to execute game builds.")
        if kind == "playtest":
            jobs.update(job_id, progress=65, message="Running headless Godot gameplay smoke test")
            result = subprocess.run([exe,"--headless","--path",str(game),"--quit-after","120"],capture_output=True,text=True,timeout=180)
            if result.returncode != 0:
                raise RuntimeError("Godot playtest failed: " + (result.stderr or result.stdout)[-3000:])
            artifact_root = folder / "artifacts" / job_id
            artifact_root.mkdir(parents=True,exist_ok=True)
            log_file = artifact_root / "playtest.log"
            log_file.write_text((result.stdout or "") + "\n" + (result.stderr or ""),encoding="utf-8")
            _save_artifacts(folder, job_id, [{"id":"playtest-log","filename":log_file.name,"path":str(log_file.relative_to(folder)),"content_type":"text/plain"}])
            jobs.update(job_id, state=__import__("core.orchestration.jobs",fromlist=["JobState"]).JobState.COMPLETED, progress=100, message="Headless Godot playtest passed (120 frames). Use the desktop Godot runtime for interactive play.", error=None)
            return
        selected = EXPORT_TARGETS.get(target)
        if not selected:
            raise RuntimeError(f"Unsupported export target: {target}")
        if target == "android":
            android = android or {}
            build_type = str(android.get("build_type") or "debug").lower()
            artifact_format = str(android.get("artifact_format") or "apk").lower()
            if build_type not in {"debug","release"}:
                raise RuntimeError("Android build type must be debug or release.")
            if artifact_format == "aab" and build_type != "release":
                raise RuntimeError("AAB output requires a release build.")
            if build_type == "release":
                required = {
                    "GODOT_ANDROID_KEYSTORE_RELEASE_PATH",
                    "GODOT_ANDROID_KEYSTORE_RELEASE_USER",
                    "GODOT_ANDROID_KEYSTORE_RELEASE_PASSWORD",
                }
                missing = [key for key in required if not os.environ.get(key)]
                if missing:
                    raise RuntimeError("Release signing is not configured on this worker. Missing protected environment variables: " + ", ".join(sorted(missing)))
                if not Path(os.environ["GODOT_ANDROID_KEYSTORE_RELEASE_PATH"]).is_file():
                    raise RuntimeError("The configured Android release keystore file is not available on this worker.")
            if artifact_format not in {"apk","aab"}:
                raise RuntimeError("Android export supports APK or AAB.")
            if artifact_format == "aab":
                selected = [("Android","android",".aab")]
            else:
                selected = [("Android","android",".apk")]
        _write_export_presets(game, selected, android)
        if target == "android":
            _apply_android_orientation(game, android)
        output_records = []
        for index,(preset,platform,suffix) in enumerate(selected):
            jobs.update(job_id, progress=65 + int(25*index/len(selected)), message=f"Exporting {platform} game with Godot")
            output = game.parent / "artifacts" / platform
            output.mkdir(parents=True,exist_ok=True)
            filename = "index.html" if platform == "web" else f"{definition.project.name.replace(' ','_')}{suffix}"
            target_file = output / filename
            export_flag = "--export-debug" if target == "android" and str((android or {}).get("build_type") or "debug").lower() == "debug" else "--export-release"
            result = subprocess.run([exe,"--headless","--path",str(game),export_flag,preset,str(target_file)],capture_output=True,text=True,timeout=1800)
            if result.returncode != 0 or not target_file.exists():
                detail = (result.stderr or result.stdout or "Godot did not produce an export file")[-3500:]
                raise RuntimeError(f"{platform} export failed. Check that the Godot {platform} export template and platform SDK are installed. {detail}")
            output_records.append({"id":platform,"filename":filename,"path":str(target_file.relative_to(folder)),"content_type":mimetypes.guess_type(filename)[0] or "application/octet-stream"})
        _save_artifacts(folder, job_id, output_records)
        jobs.update(job_id, state=__import__("core.orchestration.jobs",fromlist=["JobState"]).JobState.COMPLETED, progress=100, message="Platform export completed: " + ", ".join(item["filename"] for item in output_records), error=None)
    except Exception as exc:
        jobs.update(job_id, state=__import__("core.orchestration.jobs",fromlist=["JobState"]).JobState.FAILED, progress=100, message="NEXORA production job failed", error=str(exc))

def _run_workspace_video_analysis(job_id: str, folder: Path, jobs: Any) -> None:
    try:
        from core.movie_pipeline.worker import analyze_project
        from core.orchestration.jobs import JobState
        jobs.update(job_id,state=JobState.RUNNING,progress=5,message="Checking source clip and extracting scene keyframes")
        result=analyze_project(folder)
        keyframes=len(result.get("keyframes",[]))
        scenes=len(result.get("scene_detection",{}).get("scenes",[]))
        jobs.update(job_id,state=JobState.COMPLETED,progress=100,message=f"Video analysis complete · {scenes} scene segments · {keyframes} keyframes · creator review required",error=None)
    except Exception as exc:
        from core.orchestration.jobs import JobState
        jobs.update(job_id,state=JobState.FAILED,progress=100,message="Video intake / analysis failed",error=str(exc))

def _save_artifacts(folder: Path, job_id: str, items: list[dict]) -> None:
    root = folder / "workspace_jobs"
    root.mkdir(exist_ok=True)
    path = root / f"{job_id}.json"
    path.write_text(json.dumps({"artifacts":items},indent=2),encoding="utf-8")

def register_nexora_workspace_routes(app: Any, manager: Any, jobs: Any) -> None:
    router = APIRouter()

    @router.get("/api/v1/studio/templates")
    def list_studio_templates(request: Request):
        _owner_id(request)
        return {"templates": TEMPLATES, "source": "procedural-game-foundry"}

    @router.get("/api/v1/studio/templates/{template_id}/model")
    def get_studio_template_model(template_id: str, request: Request):
        _owner_id(request)
        model = _build_template_glb(template_id)
        return Response(content=model, media_type="model/gltf-binary", headers={"Content-Disposition": f'inline; filename="{template_id}.glb"'})

    @router.get("/api/v1/workspace/projects")
    def list_workspace_projects(request: Request):
        owner = _owner_id(request)
        rows = []
        for definition in manager.list():
            folder = manager.path_for(definition.id)
            marker = _owner_path(folder)
            if marker.is_file():
                try:
                    if json.loads(marker.read_text(encoding="utf-8")).get("user_id") != owner:
                        continue
                except (OSError,ValueError):
                    continue
            elif os.environ.get("NEXORA_AUTH_REQUIRED","").lower() in {"1","true","yes"}:
                continue
            rows.append(_row(folder,definition))
        return {"projects":rows}

    @router.post("/api/v1/workspace/projects", status_code=201)
    def create_workspace_project(payload: dict, request: Request):
        owner = _owner_id(request)
        name = str(payload.get("name") or "Untitled Game").strip()[:80]
        if not name:
            raise HTTPException(422,"Project name is required.")
        description = str(payload.get("description") or "")[:2000]
        document = payload.get("document") if isinstance(payload.get("document"),dict) else {}
        definition = manager.create(ProjectCreate(name=name,description=description,genre="science-fiction",dimension="3d"))
        folder = manager.path_for(definition.id)
        _owner_path(folder).write_text(json.dumps({"user_id":owner,"created_at":_utc()},indent=2),encoding="utf-8")
        state = {**document,"id":definition.id,"name":name,"description":description,"assets":[],"revisions":[],"version":1,"createdAt":_utc(),"updatedAt":_utc()}
        _state_path(folder).write_text(json.dumps(state,indent=2),encoding="utf-8")
        return _row(folder,definition)

    @router.get("/api/v1/workspace/projects/{pid}")
    def get_workspace_project(pid: str, request: Request):
        try: folder = manager.path_for(pid); definition = manager.load(pid)
        except FileNotFoundError: raise HTTPException(404,"Project not found")
        except ValueError as exc: raise HTTPException(400,str(exc))
        _assert_owner(folder,request)
        return _row(folder,definition)

    @router.put("/api/v1/workspace/projects/{pid}")
    def update_workspace_project(pid: str, payload: dict, request: Request):
        try: folder = manager.path_for(pid); definition = manager.load(pid)
        except FileNotFoundError: raise HTTPException(404,"Project not found")
        except ValueError as exc: raise HTTPException(400,str(exc))
        _assert_owner(folder,request)
        state = _load_state(folder,definition)
        expected = payload.get("expected_version")
        if expected is not None and int(expected) != int(state.get("version",1)):
            raise HTTPException(409,"Project version changed on the server. Reload before saving to avoid overwriting newer edits.")
        document = payload.get("document")
        if not isinstance(document,dict): raise HTTPException(422,"A project document is required.")
        state.update(document)
        state["name"] = str(payload.get("name") or document.get("name") or state.get("name"))[:80]
        state["description"] = str(payload.get("description") or document.get("description") or "")[:2000]
        saved = _write_state(folder,state)
        _sync_editor_scene_to_world(folder,definition,saved)
        # Keep the PGF project definition name/description in sync with the workspace document.
        definition_file = folder / "pgf.json"
        raw = json.loads(definition_file.read_text(encoding="utf-8"))
        raw["project"]["name"] = saved["name"]
        raw["project"]["description"] = saved["description"]
        definition_file.write_text(json.dumps(raw,indent=2),encoding="utf-8")
        return _row(folder,manager.load(pid))

    @router.delete("/api/v1/workspace/projects/{pid}")
    def delete_workspace_project(pid: str, request: Request):
        try: folder = manager.path_for(pid); manager.load(pid)
        except FileNotFoundError: raise HTTPException(404,"Project not found")
        except ValueError as exc: raise HTTPException(400,str(exc))
        _assert_owner(folder,request)
        shutil.rmtree(folder)
        return {"deleted":True,"id":pid}

    @router.get("/api/v1/workspace/projects/{pid}/movie-pipeline")
    def get_workspace_movie_pipeline(pid: str, request: Request):
        try: folder=manager.path_for(pid); manager.load(pid)
        except FileNotFoundError: raise HTTPException(404,"Project not found")
        _assert_owner(folder,request)
        from core.movie_pipeline.service import PipelineStore
        try:
            document=PipelineStore(folder).load()
            return document.model_dump(mode="json")
        except FileNotFoundError:
            return {"project_id":pid,"stages":[],"source_video":None,"analysis":None}

    @router.post("/api/v1/workspace/projects/{pid}/video-intake", status_code=202)
    async def upload_workspace_video(
        pid: str,
        request: Request,
        background: BackgroundTasks,
        file: UploadFile = File(...),
        has_video_rights: bool = Form(...),
        accepts_original_assets_only: bool = Form(...),
    ):
        try: folder=manager.path_for(pid); manager.load(pid)
        except FileNotFoundError: raise HTTPException(404,"Project not found")
        owner=_assert_owner(folder,request)
        if not has_video_rights:
            raise HTTPException(400,"Confirm that you own or have permission to use this video before ingesting it.")
        if not accepts_original_assets_only:
            raise HTTPException(400,"Confirm that NEXORA should create original assets rather than copy protected source media.")
        from core.movie_pipeline.ingestion import UploadRejected, store_upload
        from core.movie_pipeline.models import RightsDeclaration, StageId, new_pipeline
        from core.movie_pipeline.service import PipelineStore
        store=PipelineStore(folder)
        try:
            document=store.load()
        except FileNotFoundError:
            rights=RightsDeclaration(
                has_video_rights=True,
                has_photo_rights=False,
                likeness_consent=False,
                accepts_original_assets_only=True,
            )
            document=store.save(new_pipeline(pid,rights))
        if document.source_video:
            raise HTTPException(409,"A source video is already attached. Remove or replace the current source before uploading another.")
        if not document.rights.has_video_rights or not document.rights.accepts_original_assets_only:
            raise HTTPException(409,"The existing pipeline rights declaration does not allow this video workflow.")
        try:
            metadata=await store_upload(file,"video",store.folder/"uploads")
        except UploadRejected as exc:
            raise HTTPException(400,str(exc)) from exc
        document.source_video=metadata
        store.save(document)
        job=jobs.add(__import__("core.orchestration.jobs",fromlist=["Job"]).Job.create(pid))
        job_root=folder/"workspace_jobs"; job_root.mkdir(exist_ok=True)
        (job_root/f"{job.id}.owner.json").write_text(json.dumps({"user_id":owner},indent=2),encoding="utf-8")
        background.add_task(_run_workspace_video_analysis,job.id,folder,jobs)
        return {
            **job.as_dict(),
            "state":job.state.value.lower(),
            "source_video":metadata,
            "pipeline":document.model_dump(mode="json"),
        }

    @router.post("/api/v1/workspace/projects/{pid}/movie-pipeline/stages/{stage_id}/approve")
    def approve_workspace_movie_stage(pid: str, stage_id: str, payload: dict, request: Request):
        try: folder=manager.path_for(pid); manager.load(pid)
        except FileNotFoundError: raise HTTPException(404,"Project not found")
        _assert_owner(folder,request)
        from core.movie_pipeline.models import StageId
        from core.movie_pipeline.service import PipelineError, PipelineStore
        try:
            stage=StageId(stage_id)
            document=PipelineStore(folder).approve(stage,str(payload.get("note") or ""))
            return document.model_dump(mode="json")
        except (ValueError,PipelineError) as exc:
            raise HTTPException(409,str(exc)) from exc

    @router.get("/api/v1/workspace/projects/{pid}/video-analysis")
    def get_workspace_video_analysis(pid: str, request: Request):
        try: folder=manager.path_for(pid); manager.load(pid)
        except FileNotFoundError: raise HTTPException(404,"Project not found")
        _assert_owner(folder,request)
        analysis_files=sorted((folder/"movie_pipeline"/"analysis").glob("revision-*/analysis.json")) if (folder/"movie_pipeline"/"analysis").exists() else []
        if not analysis_files:
            raise HTTPException(404,"No video analysis is available yet.")
        try:
            return json.loads(analysis_files[-1].read_text(encoding="utf-8"))
        except (OSError,ValueError) as exc:
            raise HTTPException(500,"Video analysis report is unreadable.") from exc

    @router.get("/api/v1/workspace/projects/{pid}/assets")
    def list_workspace_assets(pid: str, request: Request):
        try: folder=manager.path_for(pid); manager.load(pid)
        except FileNotFoundError: raise HTTPException(404,"Project not found")
        _assert_owner(folder,request)
        return {"assets":_asset_rows(folder)}

    @router.post("/api/v1/workspace/projects/{pid}/assets", status_code=201)
    async def upload_workspace_asset(pid: str, request: Request, file: UploadFile=File(...), kind: str=Form("model"), license_name: str=Form("Creator confirms usage rights"), source: str=Form("creator-upload")):
        try: folder=manager.path_for(pid); manager.load(pid)
        except FileNotFoundError: raise HTTPException(404,"Project not found")
        _assert_owner(folder,request)
        name = (file.filename or "").replace("\\","/").split("/")[-1]
        suffix = Path(name).suffix.lower()
        if not name or suffix not in {".glb",".gltf",".bin",".png",".jpg",".jpeg",".webp",".wav",".ogg",".mp3"}:
            raise HTTPException(400,"Supported creator assets: GLB, glTF, BIN, PNG, JPG, WebP, WAV, OGG and MP3.")
        if suffix in {".glb",".gltf"} and not license_name.strip():
            raise HTTPException(400,"Provide an asset rights declaration before uploading a 3D model.")
        if len(name)>160: raise HTTPException(400,"Asset filename is too long.")
        asset_root=folder/"assets"; asset_root.mkdir(parents=True,exist_ok=True)
        destination=asset_root/name
        if destination.exists(): raise HTTPException(409,"An asset with this filename already exists. Rename it first.")
        temporary=destination.with_name(destination.name+".uploading")
        size=0
        try:
            with temporary.open("xb") as out:
                while chunk:=await file.read(1024*1024):
                    size+=len(chunk)
                    if size>MAX_ASSET_BYTES: raise HTTPException(413,"Asset exceeds the 512 MiB limit.")
                    out.write(chunk)
            temporary.replace(destination)
            if suffix in {".glb",".gltf"}:
                report=validate_gltf(destination)
                if not report["valid"]:
                    destination.unlink(missing_ok=True)
                    raise HTTPException(422,{"message":"3D model validation failed","errors":report["errors"]})
            else:
                report={"valid":True,"errors":[],"warnings":[],"stats":{}}
            asset_id=f"{destination.stem[:40]}-{uuid4().hex[:8]}"
            default_kind = "dependency" if suffix in {".bin",".png",".jpg",".jpeg",".webp"} else "source_media" if suffix in {".mp4",".mov",".mkv",".webm",".avi"} else "animation" if suffix in {".wav",".ogg",".mp3"} else "model"
            asset_kind=kind if kind in {"model","character","environment","prop","animation","dependency","source_media"} else default_kind
            record=AssetRegistry(asset_root).register(asset_id,destination.name,asset_kind,license_name or "Creator-uploaded asset",source=source,metadata={"format":suffix[1:],"size_bytes":size,"validation":report})
            return {"asset":{"id":record["asset_id"],"filename":destination.name,"content_type":mimetypes.guess_type(destination.name)[0] or "application/octet-stream","size":size,"created_at":_utc(),"status":"ready","kind":asset_kind,"sha256":record["checksum"],"metadata":record["metadata"]}}
        except HTTPException:
            temporary.unlink(missing_ok=True); raise
        except Exception as exc:
            temporary.unlink(missing_ok=True); destination.unlink(missing_ok=True)
            raise HTTPException(400,f"Asset upload failed: {exc}") from exc
        finally:
            await file.close()

    @router.get("/api/v1/workspace/projects/{pid}/assets/{asset_id}/file")
    def get_workspace_asset_file(pid: str, asset_id: str, request: Request):
        try: folder=manager.path_for(pid); manager.load(pid)
        except FileNotFoundError: raise HTTPException(404,"Project not found")
        _assert_owner(folder,request)
        item=next((row for row in AssetRegistry(folder/"assets").list() if row.get("asset_id")==asset_id),None)
        if not item: raise HTTPException(404,"Asset not found")
        path=(folder/"assets"/Path(item["path"]).name).resolve()
        if folder.resolve() not in path.parents or not path.is_file(): raise HTTPException(404,"Asset file not found")
        return FileResponse(path,media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",filename=path.name)

    @router.delete("/api/v1/workspace/projects/{pid}/assets/{asset_id}")
    def delete_workspace_asset(pid: str, asset_id: str, request: Request):
        try: folder=manager.path_for(pid); definition=manager.load(pid)
        except FileNotFoundError: raise HTTPException(404,"Project not found")
        _assert_owner(folder,request)
        manifest=AssetRegistry(folder/"assets").list()
        item=next((row for row in manifest if row.get("asset_id")==asset_id),None)
        if not item: raise HTTPException(404,"Asset not found")
        world_path=folder/"world.json"
        if world_path.is_file() and asset_id in world_path.read_text(encoding="utf-8"):
            raise HTTPException(409,"This 3D asset is used by the current scene. Remove its scene instance before deleting the asset.")
        asset_path=(folder/"assets"/Path(item["path"]).name).resolve()
        asset_path.unlink(missing_ok=True)
        index=folder/"assets"/"assets.json"
        index.write_text(json.dumps({"assets":[row for row in manifest if row.get("asset_id")!=asset_id]},indent=2),encoding="utf-8")
        return {"deleted":True,"asset_id":asset_id}

    @router.post("/api/v1/workspace/projects/{pid}/jobs", status_code=202)
    def create_workspace_job(pid: str, payload: dict, request: Request, background: BackgroundTasks):
        try: folder=manager.path_for(pid); manager.load(pid)
        except FileNotFoundError: raise HTTPException(404,"Project not found")
        owner=_assert_owner(folder,request)
        kind=str(payload.get("kind") or "")
        target=str(payload.get("target") or "desktop")
        if kind not in {"scene.generate","build.export","playtest"}: raise HTTPException(400,"Unsupported production job.")
        if kind=="build.export" and target not in EXPORT_TARGETS: raise HTTPException(400,f"Unsupported export target: {target}")
        android = payload.get("android") if isinstance(payload.get("android"),dict) else {}
        if kind=="build.export" and target=="android":
            package_id=str(android.get("package_id") or "com.nexora.game").strip().lower()
            if not re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){1,}",package_id):
                raise HTTPException(422,"Android package ID must use reverse-DNS format, e.g. com.studio.mygame.")
            if str(android.get("artifact_format") or "apk").lower()=="aab" and str(android.get("build_type") or "debug").lower()!="release":
                raise HTTPException(422,"AAB output requires a release build.")
            if str(android.get("build_type") or "debug").lower()=="release":
                required={"GODOT_ANDROID_KEYSTORE_RELEASE_PATH","GODOT_ANDROID_KEYSTORE_RELEASE_USER","GODOT_ANDROID_KEYSTORE_RELEASE_PASSWORD"}
                missing=sorted(key for key in required if not os.environ.get(key))
                if missing: raise HTTPException(409,"Android release signing is not configured on the NEXORA worker.")
                if not Path(os.environ["GODOT_ANDROID_KEYSTORE_RELEASE_PATH"]).is_file():
                    raise HTTPException(409,"The configured Android release keystore file is unavailable on the NEXORA worker.")
        job=jobs.add(__import__("core.orchestration.jobs",fromlist=["Job"]).Job.create(pid))
        job_root=folder/"workspace_jobs"; job_root.mkdir(exist_ok=True)
        (job_root/f"{job.id}.owner.json").write_text(json.dumps({"user_id":owner},indent=2),encoding="utf-8")
        background.add_task(_run_workspace_job,job.id,pid,kind,target,payload.get("android"),manager,jobs)
        return {**job.as_dict(),"state":job.state.value.lower(),"artifacts":[]}

    @router.get("/api/v1/workspace/projects/{pid}/jobs")
    def list_workspace_jobs(pid: str, request: Request):
        try: folder=manager.path_for(pid); manager.load(pid)
        except FileNotFoundError: raise HTTPException(404,"Project not found")
        _assert_owner(folder,request)
        records=[]
        with jobs._lock:
            matching=[job for job in jobs._jobs.values() if job.project_id==pid]
        for job in sorted(matching,key=lambda item:item.created_at,reverse=True):
            data=job.as_dict(); data["state"]=job.state.value.lower()
            artifact_file=folder/"workspace_jobs"/f"{job.id}.json"
            data["artifacts"]=json.loads(artifact_file.read_text(encoding="utf-8")).get("artifacts",[]) if artifact_file.is_file() else []
            records.append(data)
        return {"jobs":records}

    @router.get("/api/v1/workspace/jobs/{job_id}/artifacts")
    def get_workspace_job_artifacts(job_id: str, request: Request):
        _owner=_owner_id(request)
        for definition in manager.list():
            folder=manager.path_for(definition.id)
            metadata=folder/"workspace_jobs"/f"{job_id}.owner.json"
            if not metadata.is_file(): continue
            try: record=json.loads(metadata.read_text(encoding="utf-8"))
            except (OSError,ValueError): continue
            if record.get("user_id")!=_owner: continue
            artifact_file=folder/"workspace_jobs"/f"{job_id}.json"
            data=json.loads(artifact_file.read_text(encoding="utf-8")) if artifact_file.is_file() else {"artifacts":[]}
            artifacts=[]
            for item in data.get("artifacts",[]):
                artifacts.append({**item,"download_url":f"/api/v1/workspace/jobs/{job_id}/artifacts/{item['id']}/download"})
            return {"artifacts":artifacts}
        raise HTTPException(404,"Production job not found.")

    @router.get("/api/v1/workspace/jobs/{job_id}/artifacts/{artifact_id}/download")
    def download_workspace_job_artifact(job_id: str, artifact_id: str, request: Request):
        owner=_owner_id(request)
        for definition in manager.list():
            folder=manager.path_for(definition.id)
            metadata=folder/"workspace_jobs"/f"{job_id}.owner.json"
            if not metadata.is_file(): continue
            try: record=json.loads(metadata.read_text(encoding="utf-8"))
            except (OSError,ValueError): continue
            if record.get("user_id")!=owner: continue
            artifact_file=folder/"workspace_jobs"/f"{job_id}.json"
            if not artifact_file.is_file(): continue
            data=json.loads(artifact_file.read_text(encoding="utf-8"))
            item=next((value for value in data.get("artifacts",[]) if value.get("id")==artifact_id),None)
            if not item: raise HTTPException(404,"Artifact not found.")
            path=(folder/Path(item["path"])).resolve()
            if folder.resolve() not in path.parents or not path.is_file(): raise HTTPException(404,"Artifact file not found.")
            return FileResponse(path,media_type=item.get("content_type") or "application/octet-stream",filename=item["filename"])
        raise HTTPException(404,"Production job not found.")

    app.include_router(router)
