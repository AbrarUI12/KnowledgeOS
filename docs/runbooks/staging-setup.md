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
| **Auth0** | Tenant; an **API** (identifier = e.g. `https://api.knowledgeos.dev`, RS256); a **Regular Web Application** for the web app (callback `https://<vercel-app>/api/auth/callback/auth0`); refresh-token rotation on; RBAC off; demo users `alice`, `bob`, `hana`, `carol` with the seed emails | issuer `https://<tenant>.<region>.auth0.com/`, API identifier, app client id + secret |
| **Hugging Face** | A **public** Docker Space `knowledgeos-api-staging` (CPU basic, free) | Space URL `https://<user>-knowledgeos-api-staging.hf.space` |
| **Vercel** | Hobby account linked to the GitHub repo (project root `apps/web`) | staging URL |
| **Groq** (+ optional Gemini) | API key | key, a model id, your account's RPM/TPM/RPD limits |

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

- **Space:**
  1. Push the image to GHCR.
  2. The Space repo holds only a `Dockerfile` with `FROM ghcr.io/<owner>/knowledgeos-space:<tag>` and a `README.md` front matter (`sdk: docker`, `app_port: 7860`).
  3. Every value from `infra/space/staging.env.example` goes into Space **Variables/Secrets**.
- **Vercel:** `AUTH_*` values, the Auth0 issuer and client, and the public API base URL (= Space URL). Its production deployment acts as staging for now.
- **Seed:** `scripts/seed_demo.py` against the staging API with the Auth0 demo users.

## Limits to keep in mind

- **Spaces:** free Spaces sleep after ~48 h without traffic, and a cold start (model load) takes a few minutes. Neon scales to zero (a few seconds of cold start).
- **Groq free tier:** limits are per account; the gateway throttles to the configured RPM/TPM/RPD.
- **Evidence leaves the deployment:** `LLM_ALLOW_EXTERNAL=true` sends evidence to Groq/Gemini. That's acceptable for the synthetic demo corpus only. A KB that must stay local sets its model policy to `local_only`.
