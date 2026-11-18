"""CLI for exporting and validating Nexora Foundry Godot projects."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.movie_pipeline.release import export_game  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a Nexora Foundry game build.")
    parser.add_argument("--project", type=Path, required=True, help="Assembled Godot project directory.")
    parser.add_argument("--target", choices=("linux", "windows", "android"), required=True)
    parser.add_argument("--output", type=Path, default=Path("dist/release"))
    parser.add_argument("--godot", default=shutil.which("godot") or shutil.which("godot4") or "godot")
    parser.add_argument("--mode", choices=("debug", "release"), default="debug")
    args = parser.parse_args()
    try:
        result = export_game(args.project, args.target, args.output, args.godot, args.mode)
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps({"success": True, **result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
