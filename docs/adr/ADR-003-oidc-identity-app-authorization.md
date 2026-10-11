# ADR-003: OIDC identity, application-owned authorization

- **Status:** Accepted
- **Date:** 2026-10-12
- **Related:** plan.md §5.6, §7.2, §28.2

## Context

Implementing password storage, MFA and session security ourselves is risky and unnecessary. At the same time, KnowledgeOS authorization (organizations, roles, groups, KB and document ACLs) is domain logic that identity providers model poorly and differently.

## Decision

- **Authentication** uses standard **OIDC**. The API validates access tokens itself (signature via cached JWKS with an algorithm allowlist, `iss`, `aud`, `exp`, `nbf`, `sub`).
- **Authorization** lives entirely in KnowledgeOS: users are provisioned just-in-time by `(issuer, sub)`; memberships, roles, permission strings and ACLs are KnowledgeOS data.
- Local development uses **Keycloak** (Docker). Deployed environments use a managed free provider (**Auth0** by default). Switching providers is configuration only.

## Consequences

- No password cryptography in our code; providers are swappable.
- IdP roles/groups are not trusted for authorization (connector-sourced permissions are mapped explicitly, Session 51).
- Token issuer strings must match exactly; local Keycloak uses a fixed hostname.

## Alternatives considered

- **Custom username/password auth** — rejected: security risk and effort.
- **Authorization in the IdP (RBAC claims)** — rejected: can't express document-level ACLs; ties us to one provider.
