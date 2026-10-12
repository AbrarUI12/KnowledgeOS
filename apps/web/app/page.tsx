import {
  ArrowRight,
  BadgeCheck,
  Database,
  FileSearch,
  GitBranch,
  Layers,
  LockKeyhole,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/primitives/badge";
import { ThemeToggle } from "@/components/theme-toggle";

const REPO_URL = "https://github.com/AbrarUI12/KnowledgeOS";

const principles = [
  {
    icon: LockKeyhole,
    title: "Tenant isolation, twice",
    body: "Every tenant table carries organization_id with forced PostgreSQL row-level security. Cross-org access returns 404 and fails closed.",
  },
  {
    icon: ShieldCheck,
    title: "Authorize before generation",
    body: "Permission filters live inside the retrieval SQL. Nothing a user may not read ever reaches a model.",
  },
  {
    icon: FileSearch,
    title: "Retrieved text is untrusted",
    body: "Documents are scanned for prompt injection and passed to the model as delimited evidence, never as instructions.",
  },
  {
    icon: BadgeCheck,
    title: "Verifiable citations",
    body: "Answers cite [S1]-style aliases resolved from storage, validated after generation, and linked to the exact page and passage.",
  },
];

const pipeline = [
  "Upload (presigned, quarantined)",
  "File safety + malware scan",
  "Parse (Docling + OCR)",
  "Normalize + injection scan",
  "Structure-aware chunking",
  "Embed (Qwen3, 1024-d)",
  "Index with ACL tokens",
  "Hybrid search + RRF",
  "Rerank + pack evidence",
  "Grounded, cited answer",
];

const stack = [
  ["Frontend", "Next.js 16, React 19, Tailwind 4, Radix, Motion"],
  ["API", "FastAPI, Pydantic 2, SQLAlchemy 2 async, Alembic"],
  ["Data", "PostgreSQL 17 + pgvector + pg_trgm, forced RLS"],
  ["Workers", "Celery + transactional outbox, checkpointed stages"],
  ["Identity", "OIDC (Keycloak locally, Auth0 deployed), JWKS verification"],
  ["Models", "Qwen3-Embedding, bge-reranker-v2-m3, Groq / Gemini / Ollama"],
  ["Quality", "pytest + Testcontainers + Hypothesis, Vitest, Playwright, axe"],
  ["Budget", "$0: Vercel, Hugging Face Space, Neon, Backblaze B2, Auth0 free tiers"],
] as const;

const milestones = [
  { label: "Contracts, OIDC auth, tenant RLS, org/member/group APIs", status: "done" },
  { label: "Object storage, file-safety validation, malware scanning", status: "done" },
  { label: "Hybrid-search fusion (RRF) and synthetic demo corpus", status: "done" },
  { label: "Frontend foundation: auth, typed API client, app shell", status: "progress" },
  { label: "Ingestion pipeline: parsing, chunking, embedding, indexing", status: "next" },
  { label: "Grounded answers with streaming citations", status: "next" },
  { label: "Live staging deployment (M1)", status: "next" },
] as const;

const statusBadge = {
  done: { text: "Done", className: "bg-success-soft text-success" },
  progress: { text: "In progress", className: "bg-warning-soft text-warning" },
  next: { text: "Planned", className: "bg-surface-2 text-ink-secondary" },
} as const;

export default function Home() {
  return (
    <div className="min-h-screen bg-canvas text-ink">
      <header className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-4 py-4 sm:px-6">
        <span className="flex items-center gap-2 font-semibold">
          <Layers aria-hidden className="size-5 text-accent" />
          KnowledgeOS
        </span>
        <nav aria-label="Site" className="flex flex-wrap items-center gap-4 text-sm">
          <a className="text-ink-secondary hover:text-ink" href={REPO_URL}>
            GitHub
          </a>
          <Link className="text-ink-secondary hover:text-ink" href="/dev/primitives">
            Design system
          </Link>
          <ThemeToggle />
        </nav>
      </header>

      <main id="main-content" className="mx-auto max-w-6xl px-4 pb-24 sm:px-6">
        <section className="flex flex-col gap-6 py-16 sm:py-24">
          <Badge className="bg-accent-soft text-accent">
            Portfolio project · in active development
          </Badge>
          <h1 className="max-w-3xl text-4xl font-semibold tracking-tight sm:text-5xl">
            KnowledgeOS
          </h1>
          <p className="max-w-2xl text-lg text-ink-secondary">
            A multi-tenant, permission-aware retrieval-augmented generation platform. Organizations
            connect their documents, control who can see what, and get answers grounded only in
            evidence the asking user is allowed to read, with citations you can verify.
          </p>
          <div className="flex flex-wrap gap-3">
            <Link
              href="/demo"
              className="inline-flex h-control-lg items-center gap-2 rounded-md bg-accent px-4 text-on-accent hover:bg-accent-hover"
            >
              <Sparkles aria-hidden className="size-4" />
              Try the interactive demo
            </Link>
            <a
              href={REPO_URL}
              className="inline-flex h-control-lg items-center gap-2 rounded-md border border-line-strong bg-surface-1 px-4 hover:bg-surface-0"
            >
              <GitBranch aria-hidden className="size-4" />
              View the source
            </a>
          </div>
          <p className="text-sm text-ink-tertiary">
            The demo runs on placeholder data in your browser. The live backend (API, workers,
            models) is being deployed as milestone M1.
          </p>
        </section>

        <section aria-labelledby="principles" className="py-10">
          <h2 id="principles" className="mb-6 text-2xl font-semibold tracking-tight">
            Security model
          </h2>
          <div className="grid gap-4 sm:grid-cols-2">
            {principles.map(({ icon: Icon, title, body }) => (
              <article key={title} className="rounded-xl border border-line bg-surface-1 p-5">
                <Icon aria-hidden className="mb-3 size-5 text-accent" />
                <h3 className="mb-1 font-semibold">{title}</h3>
                <p className="text-sm text-ink-secondary">{body}</p>
              </article>
            ))}
          </div>
        </section>

        <section aria-labelledby="pipeline" className="py-10">
          <h2 id="pipeline" className="mb-6 text-2xl font-semibold tracking-tight">
            From upload to cited answer
          </h2>
          <ol className="flex flex-wrap items-center gap-2">
            {pipeline.map((step, index) => (
              <li key={step} className="flex items-center gap-2">
                <span className="rounded-md border border-line bg-surface-1 px-3 py-1.5 text-sm">
                  <span className="mr-1.5 text-ink-tertiary">{index + 1}</span>
                  {step}
                </span>
                {index < pipeline.length - 1 && (
                  <ArrowRight aria-hidden className="size-4 text-ink-tertiary" />
                )}
              </li>
            ))}
          </ol>
        </section>

        <section className="grid gap-10 py-10 lg:grid-cols-2">
          <div>
            <h2 className="mb-6 text-2xl font-semibold tracking-tight">Stack</h2>
            <dl className="divide-y divide-line rounded-xl border border-line bg-surface-1">
              {stack.map(([term, detail]) => (
                <div key={term} className="grid grid-cols-[6rem_1fr] gap-3 px-4 py-3 text-sm">
                  <dt className="font-medium">{term}</dt>
                  <dd className="text-ink-secondary">{detail}</dd>
                </div>
              ))}
            </dl>
          </div>
          <div>
            <h2 className="mb-6 flex items-center gap-2 text-2xl font-semibold tracking-tight">
              <Database aria-hidden className="size-5 text-accent" />
              Build status
            </h2>
            <ul className="flex flex-col gap-2">
              {milestones.map(({ label, status }) => (
                <li
                  key={label}
                  className="flex items-center justify-between gap-3 rounded-md border border-line bg-surface-1 px-4 py-3 text-sm"
                >
                  <span>{label}</span>
                  <Badge className={statusBadge[status].className}>
                    {statusBadge[status].text}
                  </Badge>
                </li>
              ))}
            </ul>
            <p className="mt-4 text-sm text-ink-tertiary">
              Built by a three-agent team (Claude Code, Codex, Cline) with cross-agent code review,
              contract-first interfaces and a 200+ test suite running against real PostgreSQL.
            </p>
          </div>
        </section>
      </main>

      <footer className="border-t border-line px-4 py-6 text-center text-sm text-ink-tertiary">
        KnowledgeOS ·{" "}
        <a className="underline-offset-4 hover:underline" href={REPO_URL}>
          github.com/AbrarUI12/KnowledgeOS
        </a>
      </footer>
    </div>
  );
}
