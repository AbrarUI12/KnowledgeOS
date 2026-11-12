# syntax=docker/dockerfile:1.7
#
# KnowledgeOS web (Next.js standalone). Vercel hosts the web app in deployment; this image exists
# for self-hosting and the enterprise reference deployment.
#   docker build -f infra/docker/web.Dockerfile -t knowledgeos-web .
# Build context: repository root.

FROM node:26-slim AS base
ENV PNPM_HOME=/pnpm PATH=/pnpm:$PATH NEXT_TELEMETRY_DISABLED=1
RUN corepack enable
WORKDIR /repo

FROM base AS deps
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/
COPY packages/contracts/package.json packages/contracts/
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile --filter @knowledgeos/web

FROM deps AS build
COPY apps/web apps/web
COPY packages/contracts packages/contracts
RUN pnpm --filter @knowledgeos/web build

FROM node:26-slim AS runner
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
WORKDIR /srv
RUN groupadd --gid 1001 web && useradd --uid 1001 --gid web --no-create-home web
COPY --from=build --chown=web:web /repo/apps/web/.next/standalone ./
COPY --from=build --chown=web:web /repo/apps/web/.next/static ./apps/web/.next/static
USER web
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
