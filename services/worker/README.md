# NEXORA production worker

Run the worker on a dedicated build host, not inside the lightweight API service.

## Required environment

- `DATABASE_URL`: same managed PostgreSQL database used by the API.
- `PGF_OBJECT_STORAGE_ENDPOINT`, `PGF_OBJECT_STORAGE_BUCKET`, `PGF_OBJECT_STORAGE_REGION`, `PGF_OBJECT_STORAGE_ACCESS_KEY`, `PGF_OBJECT_STORAGE_SECRET_KEY`: access to the private NEXORA R2 bucket.
- `BLENDER_BIN` (optional): absolute path to Blender; otherwise `blender` must be on PATH.
- `GODOT_BIN` (optional): absolute path to Godot 4; otherwise `godot` must be on PATH.
- Android builds additionally require Godot Android export templates, Android SDK, Java, and a working Godot Android export setup on the worker host.
- Configure a development keystore with `GODOT_ANDROID_KEYSTORE_DEBUG_PATH`, `GODOT_ANDROID_KEYSTORE_DEBUG_USER`, and `GODOT_ANDROID_KEYSTORE_DEBUG_PASSWORD`. Never use a production Play signing key for development jobs.
- `PGF_WORKER_ID` and `PGF_WORKER_POLL_SECONDS` are optional worker identity/poll tuning.

Install Python dependencies with `pip install -e ".[cloud]"`, then run:

```bash
python -m services.worker.runner
```

## Job types

- `asset.process`: downloads an owner-authorized, self-contained GLB from private R2, runs the Blender normalization/validation script, and writes a new private normalized object.
- `scene.generate`: translates the saved creator document into the native PGF schema, assembles a Godot 4 project, runs a headless editor import/check, and stores a project ZIP.
- `build.export`: performs the same scene generation/check and attempts Linux, Windows and/or Android export according to the selected target, then stores a build ZIP in R2.

Workers claim jobs transactionally with PostgreSQL `FOR UPDATE SKIP LOCKED` and a four-hour lease. An API restart does not discard queued work. Worker failure is persisted against the job. Build output is private and can only be downloaded through the authenticated artifact endpoint.

## Production release boundary

The worker creates development/test packages. Production code signing, Android Play signing, notarization, store metadata, and release promotion require separate protected release credentials and a human release approval. A completed build is not represented as a physical-device or store-release test.
