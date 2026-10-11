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
| 413 | `payload_too_large` | Request body too large |
| 415 | `unsupported_media_type` | Unsupported content type |
| 422 | `validation_failed` | Body/query validation failed; `details.errors[]` has `loc`, `msg`, `type` |
| 429 | `rate_limited` | Too many requests (`Retry-After` header when known) |
| 500 | `internal_error` | Unexpected server error |
| 501 | `not_implemented` | Contract stub (T1.0): endpoint exists with its final schema; `details.task` names the task implementing it |
| 503 | `service_unavailable` | A dependency is unavailable |

Domain-specific codes (uploads, ingestion, retrieval) are added here as sessions introduce them.
