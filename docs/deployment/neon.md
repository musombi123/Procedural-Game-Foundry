# NEXORA Neon deployment

NEXORA uses Neon Postgres for project documents, revisions, asset metadata, job
queues and build metadata. The `nexora-assets` Object Storage bucket is private
by default. The API continues to authenticate users by verifying their existing
RevelaCode bearer session; do not enable a second Neon Auth tenant unless the
product explicitly migrates identity.

## Provision

The repository declares the private bucket in `neon.ts`. In GitHub Actions,
run **Provision NEXORA Neon infrastructure** manually and enter `PROVISION`.
The workflow uses the repository secret `NEXORA` as `NEON_API_KEY`, links only
the configured `production` branch, displays the plan, then applies it.
It does not print or upload generated credentials.

The Neon project must be in a region supported by Neon Object Storage. Check
the project's region in Neon before running the workflow.

## Render API and worker environment

After provisioning, obtain the branch's Neon variables in the Neon Console or
with `neon env pull` in a trusted operator session. Set the following on BOTH
the NEXORA API service and its dedicated worker service in Render:

- `DATABASE_URL`: pooled Neon Postgres connection string.
- `AWS_ACCESS_KEY_ID`: branch-scoped Object Storage access key.
- `AWS_SECRET_ACCESS_KEY`: branch-scoped Object Storage secret.
- `AWS_ENDPOINT_URL_S3`: branch S3 endpoint.
- `AWS_REGION`: Neon region, for example `us-east-2`.
- `PGF_OBJECT_STORAGE_BUCKET=nexora-assets`.

Also configure the API service:

- `PGF_REQUIRE_CLOUD_DEPENDENCIES=true`
- `PGF_AUTH_ENFORCEMENT_ENABLED=true`
- `PGF_IDENTITY_INTROSPECTION_URL=https://revelacode.co.ke/api/auth/me`
- `PGF_CORS_ORIGINS=https://revelacode.co.ke`

Keep all database and S3 credentials server-side. Never put them in
`VITE_*` variables, frontend source, Android assets, or browser storage.
The frontend receives only the NEXORA API base URL and uses the signed-in
RevelaCode session for authenticated requests.

## Service scope

Postgres is the Neon project's built-in database. This config provisions one
private Object Storage bucket. Neon Auth is intentionally not enabled because
RevelaCode remains NEXORA's identity provider. Neon Functions are not required
because the existing FastAPI API and dedicated worker own request processing.
Neon AI Gateway is not required by the model-free game-generation pipeline.
Realtime should be enabled only when a real collaboration/subscription feature
is implemented and tested.
