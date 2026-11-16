# Local Story Intelligence

This subsystem interprets the media-analysis keyframes with a local Ollama vision model, then produces an original game brief and storyboard with a local language model.

## Local setup

1. Install Ollama locally.
2. Pull the selected models yourself after checking the exact model/weight license:
   - `ollama pull qwen2.5vl:7b`
   - `ollama pull qwen2.5:7b-instruct`
3. Set optional environment overrides:
   - `PGF_OLLAMA_URL=http://127.0.0.1:11434`
   - `PGF_VISION_MODEL=qwen2.5vl:7b`
   - `PGF_STORY_MODEL=qwen2.5:7b-instruct`

The worker accepts loopback HTTP only. It does not call cloud endpoints and never downloads models. Both models must already appear in `ollama list`.

## Run

Complete media analysis first, then call:

```http
POST /api/projects/PROJECT_ID/movie-pipeline/stages/analysis/intelligence/run
```

Poll the returned job using `GET /api/jobs/JOB_ID`. The worker writes `vision-analysis.json` and `storyboard.json` alongside the media manifest. The analysis stage remains in creator REVIEW after completion; the creator can inspect and approve or regenerate it.

The vision prompt samples up to 12 keyframes and records visual evidence, recurring figures, locations, objects and events. The story planner creates an original game concept with a player character, supporting cast, factions, enemies, items, 4-8 missions and 3-7 levels. The model output is a proposal, not verified film canon. Review and edit it before downstream asset generation.

## Hardware and licensing

7B vision and language models can require substantial RAM/VRAM and may be slow on CPU. Use smaller compatible local models by setting the environment variables. Model software, weights, training data and commercial-use terms have separate licenses; review the exact artifacts before distribution.
