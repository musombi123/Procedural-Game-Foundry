"""Deterministic world-layout planner. Emits geometry instructions, not AI-generated art."""
from __future__ import annotations
import hashlib, math, random
from typing import Any

def build_world_spec(story: dict[str, Any], *, seed: int | None = None) -> dict[str, Any]:
    setting = str(story.get("setting") or story.get("premise") or "open terrain")
    scale = story.get("world_scale", "medium")
    dimensions = {"small": 48, "medium": 96, "large": 192}.get(scale, 96)
    digest = hashlib.sha256((str(seed) if seed is not None else setting).encode()).hexdigest()
    world_seed = int(digest[:8], 16)
    rng = random.Random(world_seed)
    # A complete, navigable 3D blockout: terrain, perimeter, paths, landmarks and scatter.
    landmarks = []
    for index, name in enumerate(_landmark_names(setting)):
        angle = (2 * math.pi * index) / max(1, len(_landmark_names(setting)))
        radius = dimensions * (0.18 + 0.06 * (index % 3))
        landmarks.append({"id": f"landmark-{index+1}", "name": name,
                          "position": [round(math.cos(angle)*radius, 2), 0,
                                       round(math.sin(angle)*radius, 2)],
                          "geometry": "modular_structure", "footprint": [8, 8, 8],
                          "collision": True, "navigation_blocker": True})
    props = []
    count = max(24, dimensions // 2)
    for i in range(count):
        x, z = rng.uniform(-dimensions/2, dimensions/2), rng.uniform(-dimensions/2, dimensions/2)
        props.append({"id": f"prop-{i+1}", "geometry": rng.choice(["rock", "tree", "crate"]),
                      "position": [round(x,2), 0, round(z,2)], "scale": round(rng.uniform(.6, 1.8), 2),
                      "collision": True})
    return {"schema_version":"1.0", "generator":"pgf-deterministic-world-v1", "seed":world_seed,
            "dimensions":[dimensions, 48, dimensions], "coordinate_system":"right-handed-y-up",
            "terrain":{"type":"heightfield_mesh", "segments":64 if dimensions <= 96 else 128,
                       "amplitude":4.0, "frequency":0.035, "material":"terrain"},
            "navigation":{"generate_walkable_surface":True, "generate_collision":True,
                          "path_width":4.0, "paths":[{"from":"spawn","to":item["id"]} for item in landmarks]},
            "spawn":{"position":[0,0,0], "clear_radius":6},
            "landmarks":landmarks, "props":props,
            "lighting":{"type":"sun", "energy":2.0, "ambient_strength":0.35},
            "camera":{"mode":"third_person", "target":"player"},
            "source_story_title":story.get("title","Untitled Game"),
            "requires_creator_review":True}

def _landmark_names(setting: str) -> list[str]:
    words=[w.strip(".,:;!?").title() for w in setting.split() if len(w)>4]
    unique=list(dict.fromkeys(words))
    defaults=["Central Outpost","Ancient Gate","Ridge Observatory","Abandoned Facility"]
    return (unique[:4] + defaults)[:4]
