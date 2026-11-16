"""CLI entry point: python -m core.movie_pipeline.worker --project-dir PATH"""
import argparse
import json
from pathlib import Path
from .worker import analyze_project

def main():
    parser = argparse.ArgumentParser(description="Run local PGF movie media analysis")
    parser.add_argument("--project-dir", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(analyze_project(args.project_dir.resolve()), indent=2))

if __name__ == "__main__":
    main()
