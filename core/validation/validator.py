import json
from pathlib import Path
def validate_project(path: Path) -> dict:
    errors=[]; warnings=[]; manifest=path/"pgf.json"
    if not manifest.is_file(): errors.append("Missing pgf.json manifest")
    else:
        try: json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc: errors.append(f"Invalid manifest: {exc}")
    game=path/"game"
    if not (game/"project.godot").is_file(): warnings.append("Godot project not generated")
    else:
        for item in ["main.tscn","pgf_world.json","scripts/main.gd","scripts/player.gd","scripts/terrain.gd"]:
            if not (game/item).is_file(): errors.append(f"Missing generated file: {item}")
    return {"valid":not errors,"errors":errors,"warnings":warnings}
