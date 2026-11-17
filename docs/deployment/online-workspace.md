# NEXORA online workspace deployment

Public RevelaCode gateway: `https://revelacode.co.ke/dev_nexora`

NEXORA is a separate product and service boundary. RevelaCode supplies the authenticated frontend session and public navigation; NEXORA owns its API, project records, asset bucket, production queue and build workers. No Elimu, Shamba, Biashara or RevelaCode hub database is reused.

## Production topology

| Component | Responsibility | Runtime |
|---|---|---|
| RevelaCode frontend | NEXORA editor, bearer session, project and asset controls | Existing frontend deployment |
| NEXORA API | Identity introspection, project ownership, revisions, signed URLs, job queue | Dedicated Render Docker web service |
| PostgreSQL | Project documents, revisions, asset metadata, jobs and artifact metadata | Managed PostgreSQL with TLS |
| Cloudflare R2 | Private creator GLB/media inputs, normalized files and build artifacts | Private S3-compatible bucket |
| NEXORA worker | Blender asset processing, Godot scene generation, desktop/Android exports | Local or dedicated machine with Blender/Godot/Android SDK |

The API process does not run Blender, Godot or Android builds. The worker claims persistent jobs from PostgreSQL using `FOR UPDATE SKIP LOCKED` and leases.

## API environment

The Render blueprint is `render.yaml`. Configure these variables in the service environment. Never commit actual credentials.

| Variable | Value/purpose |
|---|---|
| `DATABASE_URL` | TLS-enabled PostgreSQL connection string |
| `PGF_OBJECT_STORAGE_ENDPOINT` | Account-specific R2 S3 endpoint |
| `PGF_OBJECT_STORAGE_BUCKET` | Private NEXORA bucket |
| `PGF_OBJECT_STORAGE_REGION` | `auto` for R2 |
| `PGF_OBJECT_STORAGE_ACCESS_KEY` | Bucket-scoped R2 access key |
| `PGF_OBJECT_STORAGE_SECRET_KEY` | Matching R2 secret |
| `PGF_IDENTITY_INTROSPECTION_URL` | `https://revelacode-backend.onrender.com/api/auth/me` |
| `PGF_AUTH_ENFORCEMENT_ENABLED` | `true` only when the configured identity service is reachable |
| `PGF_REQUIRE_CLOUD_DEPENDENCIES` | `true` |
| `PGF_CORS_ORIGINS` | Exact comma-separated origins: apex, www and frontend Render origin |

The API authenticates every workspace request by forwarding the supplied RevelaCode bearer token to the existing `/api/auth/me` endpoint. It then uses only that endpoint's canonical user ID for ownership checks. A user ID supplied in project JSON is never used as the owner.

Hosted mode exposes only `/api/v1/workspace/*`. Legacy filesystem-backed `/api/*` routes are blocked on the hosted service. `/health/live` is liveness; `/health/ready` verifies PostgreSQL and the private bucket. Do not connect the frontend until readiness returns HTTP 200.

## Private R2 configuration

1. Create a dedicated bucket, for example `nexora-foundry-assets`.
2. Keep public bucket access disabled.
3. Create credentials restricted to this bucket with object read/write/delete permissions.
4. Apply `docs/deployment/r2-cors.json` in the bucket's CORS configuration.
5. Set the API's four `PGF_OBJECT_STORAGE_*` secrets.
6. Verify the browser's signed `PUT` upload and signed `GET` download from the deployed frontend.

CORS is required because the browser uploads directly to R2 using a short-lived pre-signed URL. These signed URLs are bearer capabilities: do not log them, persist them, or expose them to another user. The API gives the browser a ten-minute upload URL and a ten-minute download URL.

## Database and migrations

The first hosted schema is created idempotently by the API for:
- `nexora_projects`: owner-scoped JSONB project documents and optimistic version number.
- `nexora_project_revisions`: immutable project snapshots.
- `nexora_assets`: object keys, checksums, size and processing state.
- `nexora_jobs`: persistent scene/asset/build jobs and worker leases.
- `nexora_artifacts`: private build and processing report references.

Backups and point-in-time recovery must be enabled at the database provider. The application does not treat Render's ephemeral filesystem as durable project storage.

## Worker installation

Run the worker on a machine with enough disk and memory to process creator assets. Start with local or dedicated hardware to avoid paying for idle GPU capacity.

Install:
- Python 3.11 and this repository's cloud dependencies.
- Blender (the worker requires a Blender executable; set `BLENDER_BIN` if it is not on `PATH`).
- Godot 4.6.1 and matching export templates (set `GODOT_BIN` if it is not on `PATH`).
- For Android export: JDK 17, Android command-line tools, platform 35, build-tools 35.0.0 and Godot Android export templates.
- A configured Android debug keystore for development builds. Production signing keys must be managed separately and never placed in the repository.

Set the same `DATABASE_URL` and private `PGF_OBJECT_STORAGE_*` secrets as the API. Optional variables are `PGF_WORKER_ID`, `PGF_WORKER_POLL_SECONDS`, `BLENDER_BIN` and `GODOT_BIN`.

```bash
python -m pip install -e ".[cloud]"
python -m services.worker.runner
```

The worker:
- downloads owner-authorized GLB assets from private R2,
- runs the Blender normalization/validation script,
- copies selected creator GLBs into the generated Godot project and instantiates them in the scene,
- runs Godot's headless import/runtime checks,
- exports Linux/Windows desktop or Android debug builds, and
- uploads private artifacts to R2 for owner-authorized signed downloads.

A queued job remains queued until a worker is actually online. A successful API response means the job was accepted, not that a build completed.

## Frontend configuration

The production frontend must be rebuilt with:

```text
VITE_NEXORA_API_URL=https://nexora-foundry-api.onrender.com
```

This public API origin is not a secret. Access tokens are read from the existing AuthContext at request time and are not stored by the NEXORA component.

## Deployment sequence

1. Provision managed PostgreSQL and private R2 bucket, credentials and CORS.
2. Create the dedicated Render API service from `render.yaml`; set the provider secrets and verify `/health/ready`.
3. Configure the dedicated worker machine and run `python -m services.worker.runner`.
4. Confirm the worker is polling and can claim a test job.
5. Rebuild and deploy RevelaCode frontend with `VITE_NEXORA_API_URL`.
6. Sign in through RevelaCode, create a NEXORA project, upload a GLB, complete the upload, run Blender processing, generate a Godot scene and retrieve a private artifact.
7. Run CI gates, then the creator acceptance playtest in `docs/testing/creator-playtest.md`.

## Test gates and release truth

The Foundry CI now covers PostgreSQL-backed API ownership/revision tests, Blender creator-asset normalization, Godot runtime generation, desktop/Android export, and an Android emulator launch smoke test. Passing CI is not equivalent to a human gameplay playthrough or a physical-device acceptance test.

Use `docs/testing/creator-playtest.md` for desktop and physical Android acceptance. A debug APK is not a Play Store release. Production signing, store metadata, privacy review, license/provenance review and release promotion require protected credentials and human approval.

## Cost and deployment boundary

The Render blueprint uses a paid Starter web service; managed PostgreSQL and R2 may incur separate costs. No provider resource is created by committing this repository. In the current code change, the API, database schema, R2 client, worker and frontend wiring are implemented, but no live Render service, PostgreSQL database, R2 bucket, secrets or worker machine have been provisioned. Those resources must be created and configured before hosted cloud operations can succeed.
