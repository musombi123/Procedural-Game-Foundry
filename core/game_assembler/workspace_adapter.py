"""Translate the RevelaCode NEXORA workspace document into the native PGF model."""
from __future__ import annotations

import re
from typing import Any

from core.project_engine.models import (
    ProjectCreate, ProjectDefinition, SceneObject, WorldDefinition, WorldDocument,
)


def build_documents(project_id: str, project: dict[str, Any]) -> tuple[ProjectDefinition, WorldDocument]:
    document = project.get("document") if isinstance(project.get("document"), dict) else {}
    settings = document.get("settings") if isinstance(document.get("settings"), dict) else {}
    scene = document.get("scene") if isinstance(document.get("scene"), dict) else {}
    raw_objects = scene.get("objects") if isinstance(scene.get("objects"), list) else []
    name = str(project.get("name") or document.get("name") or "NEXORA Game")[:80]
    description = str(project.get("description") or document.get("description") or "")[:2000]
    seed_value = document.get("seed", 784215)
    try:
        seed = max(0, min(4294967295, int(seed_value)))
    except (TypeError, ValueError):
        seed = 784215

    dimension = "2d" if str(settings.get("dimension", "3d")).lower() == "2d" else "3d"
    definition = ProjectDefinition(
        id=project_id,
        project=ProjectCreate(name=name, description=description, dimension=dimension, seed=seed),
        world=WorldDefinition(),
    )

    objects: list[SceneObject] = []
    for index, raw in enumerate(raw_objects[:500]):
        if not isinstance(raw, dict):
            continue
        object_id = re.sub(r"[^A-Za-z0-9_-]", "_", str(raw.get("id") or f"node_{index + 1}"))[:64] or f"node_{index + 1}"
        name_value = str(raw.get("name") or f"Node {index + 1}")[:80]
        kind_text = f"{raw.get('name', '')} {raw.get('type', '')}".casefold()
        kind = "beacon" if "beacon" in kind_text or "light" in kind_text else "tree" if "tree" in kind_text else "outpost" if "outpost" in kind_text or "building" in kind_text else "crate" if "crate" in kind_text else "rock"
        position = raw.get("position") if isinstance(raw.get("position"), list) else [0, 0, 0]
        rotation = raw.get("rotation") if isinstance(raw.get("rotation"), list) else [0, 0, 0]
        scale = raw.get("scale") if isinstance(raw.get("scale"), list) else [1, 1, 1]
        def bounded(value: Any, low: float, high: float, fallback: float = 0.0) -> float:
            try:
                numeric = float(value)
                if not (-1e9 < numeric < 1e9):
                    return fallback
                return min(high, max(low, numeric))
            except (TypeError, ValueError):
                return fallback
        x, y, z = (bounded(position[i] if i < len(position) else 0, -512 if i != 1 else -100, 512 if i != 1 else 100) for i in range(3))
        scale_values = [bounded(scale[i] if i < len(scale) else 1, .25, 4, 1) for i in range(3)]
        uniform_scale = min(4, max(.25, sum(scale_values) / 3))
        color = raw.get("color", "#8ba7c7")
        if not isinstance(color, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
            color = "#8ba7c7"
        objects.append(SceneObject(
            id=object_id, name=name_value, kind=kind,
            x=x, y=y, z=z,
            rotation=bounded(rotation[1] if len(rotation) > 1 else 0, -360, 360),
            scale=uniform_scale, color=color,
        ))

    world = WorldDocument(seed=seed, world=definition.world, objects=objects)
    return definition, world
