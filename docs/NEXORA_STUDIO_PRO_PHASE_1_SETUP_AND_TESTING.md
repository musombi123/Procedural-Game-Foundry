# NEXORA Studio Pro — Phase 1 setup and verification

Phase 1 covers the asset collection path, local Device Access Bond foundation, existing plan catalogue and Pochi payment safety. It does not claim that the Local Engine resource ceilings are enforced by every job runner yet.

## Files changed in this phase

- `core/nexora_workspace/api.py` — merges registered project assets with generated files under `movie_pipeline/` and serves generated IDs through the owner-checked asset route.
- `apps/web/src/AssetCollectionCenter.tsx` — asset collection loading/error/empty states, re-scan, search, filters, upload, preview, used-in-level labels, grid/list views.
- `services/worker/device_bond.py` — local-only consent policy, disabled by default, persistent limits and revocation.
- `services/worker/local_agent.py` — authenticated GET/PUT endpoints for the local Device Access Bond.
- `core/nexora_workspace/creator_workflow.py` — persist 24-hour Pochi invoice expiry, reject expired claims/verifications and reused receipt codes, and require the privileged reconciler to submit the independent merchant-side M-Pesa receipt code and amount. The merchant code must exactly match the customer's submitted code before entitlement activation.
- `core/nexora_workspace/desktop_factory.py`, `core/nexora_workspace/desktop_api.py` — project-local ordered Level Manager manifest API.
- `services/worker/workload_guard.py` — fail-closed Device Access Bond check before local production workload preflight.
- `tests/unit/test_workspace_asset_collection.py`, `tests/test_device_bond.py`, `tests/test_creator_payment_safety.py` — regression coverage.
- `docs/NEXORA_STUDIO_PRO_PHASES_0_9_TRACKER.md` — implementation and acceptance status.

## Local test commands

From the repository root:

```powershell
python -m pip install -e ".[dev]"
pytest -q tests/unit/test_workspace_asset_collection.py tests/test_device_bond.py tests/test_creator_payment_safety.py tests/test_local_compute_policy.py tests/test_level_manager.py
pytest -q
```

Web build:

```powershell
cd apps/web
npm install
npm run build
```

## Device Access Bond API smoke test

Start the Local Agent on the creator's computer, pair it with the NEXORA account, then use the bearer token returned by `POST /pair`.

```powershell
$headers = @{ Authorization = "Bearer $localAgentToken" }
Invoke-RestMethod http://127.0.0.1:8765/device-access-bond -Headers $headers
$body = @{
  enabled = $true
  cpu_percent = 70
  ram_percent = 70
  gpu_percent = 70
} | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8765/device-access-bond -Method Put -Headers $headers -ContentType "application/json" -Body $body
```

Revoke permission by sending `enabled = $false`. The local record is stored in the Local Agent data directory, not in Render. The API is a consent/policy foundation; heavy job launchers still need to enforce the bond before allocating resources.

## Asset Collection manual acceptance

1. Open a project with generated artifacts under `movie_pipeline/player`, `environment`, `actors-props`, or `audio`.
2. Open Asset Collection Center and press **Re-scan assets**.
3. Confirm generated assets appear with a Generated marker and stage metadata.
4. Open GLB/glTF, image and audio previews; confirm the browser requests the project asset file route.
5. Confirm generated files cannot be deleted from the collection.
6. Confirm uploaded project assets still appear and remain deletable only when not referenced by the world.
7. Confirm **Used in level** appears for assets referenced by the active world.

## Pochi payment acceptance

1. Create checkout and verify the returned invoice expiry is 24 hours from creation.
2. Submit the exact amount and a receipt code before expiry; the payment must remain claimed/pending.
3. Submit the same receipt code on a second payment; expect HTTP 409.
4. Attempt to claim or verify an expired payment; expect HTTP 410.
5. The privileged reconciler must send the M-Pesa code and amount copied from the merchant's own received-payment record in the JSON body, for example `{\"mpesa_receipt\":\"QWE123456\",\"paid_amount_kes\":499}`. The exact normalized code and amount must match the customer claim and invoice; otherwise verification returns HTTP 409 and access stays locked.
6. Verify only within the 24-hour expiry period. Entitlement activates only after both sides match and the privileged verification succeeds.

Production still requires `NEXORA_DATABASE_URL`, `NEXORA_POCHI_MERCHANT_NUMBER`, `NEXORA_PLAN_PRICES_KES` and `NEXORA_PAYMENT_VERIFICATION_SECRET` to be configured privately on the NEXORA API service.

## Not complete in Phase 1

- The Device Access Bond is not yet enforced in every job runner; CPU/GPU/RAM live telemetry and pause/resume are not yet implemented.
- Export-specific price quotes, bundle pricing, signed single-use export tokens and admin reconciliation UI remain.
- The asset API fix has regression tests, but a browser-based test on a real generated project is still required.
- The full Phase 1 suite must pass on the current branch before Phase 2 starts.


## Phase 2/3 local API smoke checks

After pairing the Local Agent and opening a project, the local desktop API exposes:

- `GET /api/v1/desktop/projects/{project_id}/levels` — returns the default Level 1 manifest when none has been saved.
- `PUT /api/v1/desktop/projects/{project_id}/levels` — saves an ordered manifest with 1–100 unique levels, difficulty, state and shared asset IDs. Data is stored locally in the project's `.nexora/levels.json`.

The Level Manager API is a backend foundation; the interactive Level Manager screen and multi-level export integration are not yet complete.

The Device Access Bond must be enabled on the paired computer before local production workload preflight succeeds. Revoking the bond blocks subsequent production job starts. The current implementation returns the selected resource ceilings to the workload caller; live CPU/RAM/GPU throttling and pause/resume controls are still pending.
