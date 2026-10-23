# Staging setup (M1): free-tier accounts → Space image → live demo

> Fast-track C2/C3 (session.md S32–S33, ADR-008). Every service is free and none needs a card.
> **Secrets never go into git, docs or chat.** They go only into the Hugging Face Space secrets,
> the Vercel project settings, or your local git-ignored `.env.staging`. Variable names are in
> [`infra/space/staging.env.example`](../../infra/space/staging.env.example).

## 1. Accounts the user creates (≈30 min)

| Service | What to create | Values you'll need later |
|---|---|---|
| **Neon** | Project `knowledgeos`, branch `staging` (Postgres 17) | host, database name |
| **Backblaze B2** | Private buckets `kos-staging-quarantine`, `kos-staging-trusted`, `kos-staging-artifacts`; one application key restricted to those three buckets | S3 endpoint `https://s3.<region>.backblazeb2.com`, region, key id, key |
| **Auth0** | Tenant; an **API** (identifier = e.g. `https://api.knowledgeos.dev`, RS256); a **Regular Web Application** for the web app (callback `https://<vercel-app>/api/auth/callback/oidc` (Auth.js keeps the provider id `oidc`; Vercel env: [apps/web/docs/staging-auth.md](../../apps/web/docs/staging-auth.md))); refresh-token rotation on; RBAC off; demo users `alice`, `bob`, `hana`, `carol` with the seed emails | issuer `https://<tenant>.<region>.auth0.com/`, API identifier, app client id + secret |
| **Hugging Face** | A **public** Docker Space `knowledgeos-api-staging` (CPU basic, free) | Space URL `https://<user>-knowledgeos-api-staging.hf.space` |
| **Vercel** | Hobby account linked to the GitHub repo (project root `apps/web`) | staging URL |
| **Groq** (+ optional Gemini) | API key | key, a model id, your account's RPM/TPM/RPD limits |

### Auth0: put the email in access tokens (≈5 min)

Auth0 access tokens carry no `email`, but the API needs a verified email to accept invitations (the demo seed adds Bob, Hana and Carol that way). In **Actions → Library → Build custom → Login / Post Login**, create `knowledgeos-profile-claims`:

```js
exports.onExecutePostLogin = async (event, api) => {
  const ns = "https://knowledgeos.dev/";
  api.accessToken.setCustomClaim(`${ns}email`, event.user.email);
  api.accessToken.setCustomClaim(`${ns}email_verified`, event.user.email_verified);
  api.accessToken.setCustomClaim(`${ns}name`, event.user.name);
};
```

Deploy it, add it to the **Login** trigger, and set `OIDC_CLAIM_NAMESPACE=https://knowledgeos.dev/` in the Space. Then mark each demo user's email as verified: users created in the dashboard start unverified (Management API `PATCH /api/v2/users/{id}` with `{"email_verified": true}`, or the API Explorer).

## 2. Database roles (Neon, ≈5 min)

1. Open the Neon SQL editor on the `staging` branch as the default role.
2. Paste [`infra/neon/bootstrap.sql`](../../infra/neon/bootstrap.sql) and replace the three password placeholders with generated values.
3. Run it. The final query must show `rolsuper = false` and `rolbypassrls = false` for all three roles.
4. Build three **direct** (non-pooled) connection strings in the form `postgresql+asyncpg://<role>:<password>@<host>/<db>?ssl=require`:
   - `DATABASE_URL` for `knowledgeos_app`;
   - `DATABASE_MIGRATION_URL` for `knowledgeos_owner`;
   - `DISPATCHER_DATABASE_URL` for `knowledgeos_dispatcher`.

The Space runs `alembic upgrade head` at start (staging only). The API's readiness check fails if the runtime role can bypass RLS or owns tables.

## 3. B2 CORS (≈5 min)

Browsers upload straight to B2 with presigned URLs, so the bucket needs S3 CORS allowing `PUT` and `GET` from the Vercel staging origin and `http://localhost:3000`. The headers to allow are `content-type`, `content-length` and `x-amz-*`. Set it with the B2 CLI (`b2 bucket update --cors-rules …`) or the S3 `PutBucketCors` API. Add a lifecycle rule that deletes quarantine objects after 7 days.

## 4. Prove the image locally (`make space-smoke`, Claude runs it)

```bash
cp infra/space/staging.env.example .env.staging   # git-ignored; fill in the values
make space-build                                  # worker image + all-in-one image (~5–6 GB, models baked)
make space-smoke                                  # starts it detached, waits for /health/ready = 200
docker logs -f kos-space                          # api, workers, dispatcher, beat, redis, clamd
```

Done when readiness is green against the real Neon, B2 and Auth0, and an upload through the API reaches `READY` with an answer from Groq. The C3 smoke script automates that check.

## 5. Deploy (C3)

1. **Image:**
   - Actions → "Space image" → Run workflow. It pushes `ghcr.io/abrarui12/knowledgeos-space:<sha>` and `:staging`.
   - After the first push, set the GHCR package to **public** (Package settings → visibility), so the free Space can pull it without a token.
2. **Space repo:**
   - copy [`infra/space/Dockerfile`](../../infra/space/Dockerfile) (`FROM` the GHCR tag) and [`infra/space/README.md`](../../infra/space/README.md) (`sdk: docker`, `app_port: 7860`);
   - put every value from `infra/space/staging.env.example` into Space **Variables / Secrets**;
   - the Space builds in seconds and boots: migrations, then all processes.
3. **Vercel:**
   - project root `apps/web`;
   - `AUTH_*` values with the Auth0 issuer, client id and secret, the audience = the Auth0 API identifier, and `NEXT_PUBLIC_API_URL` = the Space URL;
   - its production deployment acts as staging for now;
   - add the Vercel URL to the Space's `WEB_ORIGINS` and to B2 CORS.
4. **Seed:** sign in once as each demo user so they exist in Auth0, then run:
   ```bash
   KOS_TOKEN_ALICE=… KOS_TOKEN_BOB=… KOS_TOKEN_HANA=… KOS_TOKEN_CAROL=…      uv --directory apps/api run python ../../scripts/seed_demo.py --api https://<space>.hf.space --wait
   ```
   Tokens come from the Auth0 API test console or a signed-in browser session; they're never printed.
5. **Smoke:**
   ```bash
   KOS_SMOKE_TOKEN=… uv --directory apps/api run python ../../scripts/smoke.py      --api https://<space>.hf.space --issuer https://<tenant>.<region>.auth0.com/
   ```

## Limits to keep in mind

- **Spaces:** free Spaces sleep after ~48 h without traffic, and a cold start (model load) takes a few minutes. Neon scales to zero (a few seconds of cold start).
- **Groq free tier:** limits are per account; the gateway throttles to the configured RPM/TPM/RPD.
- **Evidence leaves the deployment:** `LLM_ALLOW_EXTERNAL=true` sends evidence to Groq/Gemini. That's acceptable for the synthetic demo corpus only. A KB that must stay local sets its model policy to `local_only`.
