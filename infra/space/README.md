---
title: KnowledgeOS API (staging)
emoji: 📚
colorFrom: green
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

KnowledgeOS backend for the staging demo: API, ingestion workers, dispatcher, scheduler, Redis
and ClamAV in one container (ADR-008). Configuration comes from this Space's Variables and
Secrets; see `infra/space/staging.env.example` in the KnowledgeOS repository. Data access is
protected by the app's own OIDC authentication and row-level security, so the Space is public.
