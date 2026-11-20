# NEXORA Studio Pro — standalone frontend

This app is deployed independently from RevelaCode. It mounts only the NEXORA workspace and its independent NEXORA registration/sign-in screen. It does not import RevelaCode's App, AuthProvider, StartModal, dashboard shell, or session.

## Local development

```bash
npm install
npm run dev
```

Set `VITE_NEXORA_API_URL` to the NEXORA API origin. The workspace defaults to `https://nexora-foundry-api.onrender.com`.

## Render Static Site

- Repository: `musombi123/Procedural-Game-Foundry`
- Branch: `main`
- Root Directory: `apps/nexora-frontend`
- Build Command: `npm install && npm run build`
- Publish Directory: `dist`
- Environment: `VITE_NEXORA_API_URL=https://nexora-foundry-api.onrender.com`
- Custom Domain: `nexora.revelacode.co.ke`

The NEXORA API must allow this exact browser origin in `NEXORA_CORS_ORIGINS`:
`https://nexora.revelacode.co.ke`

The API, database, authentication routes and payment/entitlement service remain NEXORA-owned.
