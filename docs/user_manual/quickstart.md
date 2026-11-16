# Quick start

Install Python 3.11+, create a virtual environment, run pip install -e ".[dev]", then uvicorn services.api.main:app --reload. Open http://127.0.0.1:8000/docs. POST /api/projects creates a project. POST /api/projects/{id}/generate starts generation. Poll GET /api/jobs/{job_id} until COMPLETED or FAILED. Open the generated game/ folder in Godot 4 and press Play.

Install Godot 4 separately. Configure export presets and platform SDKs before exporting.