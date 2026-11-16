# Local Media Analysis Worker

The first executable worker for the movie-to-game pipeline uses local FFmpeg tooling only; it does not call a hosted API or download model weights.

## Requirements

- FFmpeg and FFprobe available on PATH.
- Optional transcription: install `faster-whisper` and set `PGF_WHISPER_MODEL` to an already-installed model identifier/path. Device and compute type can be selected with `PGF_WHISPER_DEVICE` and `PGF_WHISPER_COMPUTE_TYPE`. The first run may download model weights if the selected identifier is not cached; use a local model directory for strictly offline operation.

## Run

From the repository root:

```bash
python -m core.movie_pipeline.worker --project-dir .pgf-data/projects/PROJECT_ID
```

Or start it through the API:

```http
POST /api/projects/PROJECT_ID/movie-pipeline/stages/analysis/run
```

The API returns a normal PGF job id; poll `GET /api/jobs/{job_id}`. Successful analysis writes `movie_pipeline/analysis/revision-N/analysis.json`, keyframe JPEGs and (when enabled) `transcript.json`. The pipeline enters REVIEW only after the manifest is written. Scene timestamps are FFmpeg scene-score candidates, not a semantic understanding of the film. If scene scoring yields no timestamps, the worker samples evenly spaced frames. Output is capped at 24 keyframes by default.

## Deliberate boundaries

- Missing FFmpeg/FFprobe fails the job with a useful error; no fake metadata is produced.
- faster-whisper is optional and skipped unless explicitly configured.
- Vision-language understanding, narrative synthesis, character generation and game construction are not yet executed by this worker.
- Keep source video in the project-private upload directory; do not expose it through static web hosting.
