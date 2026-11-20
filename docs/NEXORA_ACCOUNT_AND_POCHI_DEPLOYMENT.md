# NEXORA account, subscription and Pochi deployment

NEXORA is an independent product. It does not use RevelaCode login sessions, RevelaCode subscription entitlements, or RevelaCode collection credentials.

## Required backend environment

Configure these on the NEXORA API service (not on the RevelaCode backend):

| Variable | Purpose |
| --- | --- |
| `NEXORA_DATABASE_URL` | Private Neon PostgreSQL connection string. This is required for account sessions, payments and entitlements. |
| `NEXORA_AUTH_REQUIRED` | Set to `true` in production. |
| `NEXORA_POCHI_MERCHANT_NUMBER` | `0742466828` — the NEXORA Pochi la Biashara receiving number supplied by the owner. |
| `NEXORA_PLAN_PRICES_KES` | JSON object with the owner-approved KES prices for each plan. |
| `NEXORA_PAYMENT_VERIFICATION_SECRET` | High-entropy secret held only by the NEXORA server/operator. |
| `NEXORA_CORS_ORIGINS` | Comma-separated NEXORA frontend origins only. Production: `https://revelacode.co.ke`; local development: `http://localhost:5173,http://127.0.0.1:5173`. |
| `NEXORA_SESSION_DAYS` | Optional session lifetime (default 30 days, capped at 90). |

Use the Neon connection string in a private Render environment variable. Never put credentials, merchant secrets or the connection string in Vite's `.env.production`, frontend source, a public repository, or the browser.

Set the NEXORA Render environment variable to this exact string value (preserve the leading zero):

`NEXORA_POCHI_MERCHANT_NUMBER=0742466828`

The number is a customer-facing payment destination. Do not put it in Vite frontend source or use it as a secret.

Example price-variable structure (replace every value with approved prices before enabling checkout):

```json
{"basic": 0, "standard": 0, "pro": 0, "studio": 0}
```

All four prices must be positive integers in KES. Leaving prices unset or zero keeps checkout unavailable.

## Independent NEXORA identity

- `POST /api/v1/auth/register` creates an NEXORA account.
- `POST /api/v1/auth/login` issues an independent NEXORA bearer session.
- `GET /api/v1/auth/me` validates the current NEXORA session.
- `POST /api/v1/auth/logout` revokes that session.

Passwords are stored as PBKDF2-HMAC-SHA256 hashes. Session tokens are stored as SHA-256 digests. The identity layer intentionally reads only `NEXORA_DATABASE_URL`; it does not fall back to a generic `DATABASE_URL` that could belong to RevelaCode.

## Pochi la Biashara collection and reconciliation

The customer checkout flow displays the NEXORA Pochi merchant number, payment reference and exact amount. The customer pays using the M-PESA app or `*334#`, then submits the M-PESA receipt reference to NEXORA.

Submitting a receipt does **not** activate the subscription. The receipt claim remains pending until an authorised operator reconciles the received payment against the Pochi merchant transaction/statement and verifies it through:

`POST /api/v1/creator-flow/payments/{payment_id}/verify`

The verification request must include:
- A valid NEXORA bearer session.
- `X-Nexora-Payment-Secret: <NEXORA_PAYMENT_VERIFICATION_SECRET>`.

Keep the verification secret out of the frontend and do not send it to a customer. Only reconcile a receipt after confirming the actual incoming payment, amount, payer and merchant reference in the Pochi account. The current flow deliberately does not claim to have a customer-to-Pochi automatic callback or STK push integration. Safaricom's Pochi customer guidance lists M-PESA App, USSD `*334#`, and the Safaricom SIM Toolkit as ways for customers to pay a Pochi merchant; the merchant uses the same M-PESA mobile number for the Pochi wallet. See the [Safaricom Pochi la Biashara product guidance](https://www.business.safaricom.co.ke/products/pochi-la-biashara) and the [Safaricom Daraja Business To Pochi API catalogue](https://developer.safaricom.co.ke/apis/BusinessToPochi). Do not assume a Business-To-Pochi disbursement API is an inbound collection callback.

## Existing projects

Cloud projects created before the NEXORA account boundary may contain legacy RevelaCode owner IDs. They are not automatically assigned to the first NEXORA user who registers. Migrate each legacy project only after confirming its rightful owner; new projects are recorded against the NEXORA account ID.

## Go-live checklist

- [ ] Provision the private Neon database for NEXORA and set `NEXORA_DATABASE_URL`.
- [ ] Set `NEXORA_AUTH_REQUIRED=true` on the production API.
- [ ] Confirm the Pochi line is enrolled and set `NEXORA_POCHI_MERCHANT_NUMBER`.
- [ ] Set the final four plan prices in `NEXORA_PLAN_PRICES_KES`.
- [ ] Generate and privately store `NEXORA_PAYMENT_VERIFICATION_SECRET`.
- [ ] Confirm CORS includes the exact production NEXORA entry origin.
- [ ] Register a test NEXORA account, sign in/out, and verify that a second account cannot see the first account's projects.
- [ ] Test a low-value incoming Pochi payment, reconcile the real statement entry, and verify the entitlement only after matching the receipt.


## Frontend ownership and public path

NEXORA's independent frontend source is maintained in the existing
RevelaCode frontend repository at
`musombi123/RevelaCode-Frontend/apps/nexora`. It has a separate Vite
configuration, `index.html`, React startup entry, account gate, session
storage and API client. It does not mount inside RevelaCode's React router
or use RevelaCode authentication providers.

NEXORA does not have its own Render frontend service. The existing
RevelaCode Render Static Site builds NEXORA separately into
`public/dev_nexora` and then publishes it alongside the RevelaCode root
application. Its public URL is
`https://revelacode.co.ke/dev_nexora`.

The existing RevelaCode Render Static Site must have these Rewrite rules
above the broad SPA fallback:

| Source | Destination |
| --- | --- |
| `/dev_nexora` | `/dev_nexora/index.html` |
| `/dev_nexora/*` | `/dev_nexora/index.html` |

The browser remains on the RevelaCode apex domain. Static NEXORA assets
under `/dev_nexora/assets/` are served directly from the published
directory when present.

Set the NEXORA API's `NEXORA_CORS_ORIGINS` to
`https://revelacode.co.ke` plus the local NEXORA development origins.
The API continues to use its own bearer sessions, Neon database, payment
reconciliation and entitlements. CORS is an origin policy, not an
authentication boundary; account authorization remains enforced by NEXORA.
