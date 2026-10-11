# Acme Corp System Architecture

## Overview

- The system uses a microservices architecture.
- Services communicate via REST APIs and message queues.

## Database Layer

- PostgreSQL with pgvector for vector search.
- Row-level security for multi-tenant isolation.
- Connection pooling via pgbouncer.

## Authentication

- OIDC-based authentication via Keycloak.
- JWT tokens with short expiry.
- Role-based access control.
