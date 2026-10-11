# ADR-006: Provider abstraction

- **Status:** Accepted
- **Date:** 2026-10-12
- **Related:** plan.md §3 (principle 5), §25, §28.3

## Context

Models, storage, identity and search backends change often (and free tiers change even more often). Some knowledge bases must never send content to external providers. Hard-coding providers would spread vendor logic and make privacy policy unenforceable.

## Decision

Every external capability sits behind an interface in `app/providers/`:

- `LLMProvider` (`generate`, `stream`), `EmbeddingProvider` (`embed_documents`, `embed_query`), `RerankerProvider` (`rerank`), `SearchBackend`, `ObjectStore`, `IdentityVerifier`, `MalwareScanner`.
- Each provider declares whether it is **external** (data leaves the deployment).
- Feature code obtains providers only through a **policy-enforcing router** (Session 53) that checks the KB model policy and document classification before any call. Default deny.
- Model IDs live in configuration and are recorded on index generations and query runs; they are never business rules in code.
- Generation uses one **OpenAI-compatible** adapter that covers Ollama, Groq, Gemini and OpenRouter.
- **No silent embedding substitution:** query embeddings always use the active index generation's model.

## Consequences

- Swapping a provider is configuration plus at most one adapter.
- Local-only knowledge bases can be proven to make zero external calls (Session 54).
- Small overhead of interface definitions and fakes for tests (which also make tests deterministic).

## Alternatives considered

- **Direct SDK calls in feature code** — rejected: no single enforcement point for privacy policy.
- **A heavy framework (LangChain-style) as the core abstraction** — rejected: hides control over prompts, retries and data flow.
