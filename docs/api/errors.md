# API error codes

Every error response uses one envelope:

```json
{
  "error": {
    "code": "not_found",
    "message": "Human-readable, safe to show",
    "request_id": "0849c282-f7d5-4247-8c42-a86625bf6e45",
    "details": {}
  }
}
```

- `code` is **stable** and machine-readable. Clients branch on `code`, never on `message`.
- `request_id` matches the `X-Request-ID` response header and appears in server logs and traces.
- Validation errors never echo the submitted input (it may contain secrets).
- 500 responses never include exception messages or stack traces.

| HTTP | `code` | Meaning |
|---|---|---|
| 400 | `bad_request` | Malformed request |
| 401 | `unauthorized` | Missing or invalid credentials |
| 403 | `forbidden` | Authenticated but not allowed |
| 404 | `not_found` | Resource doesn't exist **or** isn't visible to the caller (cross-tenant access also returns 404) |
| 405 | `method_not_allowed` | Wrong HTTP method |
| 409 | `conflict` | Conflicts with current state |
| 409 | `slug_taken` | Organization slug already in use |
| 409 | `last_owner` | The change would leave the organization without an owner |
| 409 | `already_member` | The invited or joining person is already a member |
| 409 | `group_name_taken` | A group with that name exists in the organization |
| 409 | `idempotency_key_reused` | The `Idempotency-Key` was used for a different request (or the original is still in flight) |
| 410 | `invitation_expired` | The invitation link has expired |
| 410 | `upload_expired` | The upload's presigned window passed; start a new upload |
| 409 | `upload_not_received` | `complete` was called before the file was PUT to the presigned URL |
| 409 | `kb_archived` | The knowledge base is archived |
| 413 | `file_too_large` | Declared or received size exceeds `UPLOAD_MAX_BYTES` (`details.max_bytes`) |
| 422 | `unsupported_file_type` | Extension not in the allowlist (plan §5.3) |
| 422 | `size_mismatch` | Received object size differs from the declared size; the object is discarded |
| 403 | `invitation_email_mismatch` | The signed-in email doesn't match the invitation |
| 413 | `payload_too_large` | Request body too large |
| 415 | `unsupported_media_type` | Unsupported content type |
| 422 | `invalid_principal` | An ACL entry names a user, group or role that doesn't belong to the organization (`details.principals`) |
| 422 | `unsupported_filter` | A search filter with no indexed metadata yet (`tags`, `department`) |
| 422 | `validation_failed` | Body/query validation failed; `details.errors[]` has `loc`, `msg`, `type` |
| 429 | `rate_limited` | Too many requests (`Retry-After` header when known) |
| 500 | `internal_error` | Unexpected server error |
| 501 | `not_implemented` | Contract stub (T1.0): endpoint exists with its final schema; `details.task` names the task implementing it |
| 503 | `service_unavailable` | A dependency is unavailable (also: answer generation not configured, or no model allowed by the knowledge base's model policy) |
| 503 | `generation_failed` | The answer model failed or timed out; no partial answer is returned (`/query`; the stream sends it as an `error` event) |

Domain-specific codes keep the HTTP status of their generic parent (`last_owner` is a 409 like `conflict`), so clients can fall back to the status. Uploads, ingestion and retrieval codes are added as sessions introduce them.

**Idempotency (plan §26.1):** `POST /v1/organizations` and `POST .../groups` accept an `Idempotency-Key` header (8–200 chars, per user, kept for `IDEMPOTENCY_TTL_HOURS`). Retrying with the same key and body returns the original status and body; a failed request doesn't consume the key. Invitations deliberately don't: replaying one would mean storing its bearer token. A retried invitation issues a fresh link and revokes the earlier pending one.
