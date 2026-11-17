# Nexora online workspace — platform foundation

Public entry point: `https://revelacode.co.ke/dev_nexora`

Product identity, source code, project ownership and customer data remain NEXORA-owned. The RevelaCode domain is only the public gateway.

## Stage 1 deployment topology

- Static workspace: served from the portfolio/site host at `/dev_nexora`.
- API: separate Render service, `nexora-foundry-api`, built from this repository's Dockerfile.
- Relational metadata: managed PostgreSQL, supplied through `DATABASE_URL`.
- Binary assets: Cloudflare R2 (S3-compatible), supplied through the `PGF_OBJECT_STORAGE_*` variables.
- Heavy Blender/Godot work: local or dedicated build workers. The web API must not pretend that a web dyno has Blender, Godot, Android SDK or a GPU.

## Required secrets

Set these in the API host's secret/environment settings. Never commit actual credentials.

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string (TLS-enabled provider URL) |
| `PGF_OBJECT_STORAGE_ENDPOINT` | R2 S3 endpoint |
| `PGF_OBJECT_STORAGE_BUCKET` | Private bucket name |
| `PGF_OBJECT_STORAGE_ACCESS_KEY` | R2 access key ID |
| `PGF_OBJECT_STORAGE_SECRET_KEY` | R2 secret access key |
| `PGF_OBJECT_STORAGE_REGION` | Usually `auto` for R2 |
| `PGF_CORS_ORIGINS` | Comma-separated exact browser origins |
| `PGF_REQUIRE_CLOUD_DEPENDENCIES` | Must be `true` on hosted API |

The Render blueprint intentionally uses a paid Starter service. A free sleeping service is unsuitable for a responsive creator workspace. It does not provision a Render disk: the API's existing file-backed project manager is development-only and must not be treated as durable hosted storage.

## Readiness and release gates

- `GET /health/live` reports process liveness only.
- `GET /health/ready` checks PostgreSQL with `SELECT 1` and verifies the configured object-store bucket with `HeadBucket`. It returns HTTP 503 if a required dependency is missing or unreachable.
- Hosted project and asset routes remain unavailable until Stage 2 adds verified identity, project ownership and authorization enforcement. Do not set `PGF_AUTH_ENFORCEMENT_ENABLED=true` before that work is implemented and tested.
- The current project manager writes to the local filesystem. Do not expose its unauthenticated project, upload, revision or build routes publicly, and do not use `/tmp` as persistent project storage.
- Object-store writes, signed download URLs, PostgreSQL project/revision migrations, tenant isolation and retention policies are Stage 2/asset-pipeline integration work. Readiness checks prove connectivity, not those capabilities.

## Deployment sequence

1. Create a private R2 bucket and scoped credentials. Disable public bucket access.
2. Provision managed PostgreSQL and require TLS.
3. Create the Render web service from this repository using `render.yaml`; add the secrets above.
4. Verify `/health/live` and `/health/ready` before connecting the browser.
5. Keep public API routes blocked until Stage 2 authentication and ownership controls pass security tests.
6. Configure the website host's reverse proxy/path routing for `/dev_nexora` only after the workspace build is merged and deployed.

No service is deployed merely by adding these files. Host credentials, DNS/path routing and provider-side resource creation require owner action.
