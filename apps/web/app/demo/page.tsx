"use client";

import Link from "next/link";
import { useState } from "react";
import { ThemeToggle } from "@/components/theme-toggle";

const sources = [
  {
    id: "S1",
    title: "Employee handbook · 2026",
    library: "People",
    page: 12,
    text: "Eligible employees receive 16 weeks of paid parental leave. Submit a leave request at least 30 days before the expected start date.",
  },
  {
    id: "S2",
    title: "Leave request guide",
    library: "People",
    page: 3,
    text: "Send your proposed dates to your manager and People Operations. People Operations confirms eligibility and records the approved leave dates.",
  },
  {
    id: "S3",
    title: "Engineering runbook",
    library: "Engineering",
    page: 7,
    text: "Before an extended absence, assign an on-call backup and document service ownership and open incidents.",
  },
];

// Placeholder until the interactive demo lands (Codex replaces this file).
export default function DemoWalkthrough() {
  const [view, setView] = useState("Ask");
  const [answered, setAnswered] = useState(false);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<(typeof sources)[number] | null>(null);
  return (
    <main
      id="main-content"
      className="mx-auto min-h-screen max-w-7xl bg-canvas px-5 py-6 text-ink md:px-8"
    >
      <header className="mb-10 flex flex-wrap items-center justify-between gap-4 border-b border-line pb-5">
        <Link href="/" className="font-semibold">
          KnowledgeOS / Walkthrough
        </Link>
        <div className="flex items-center gap-4">
          <Link href="/dev/primitives" className="text-sm text-accent">
            Design system
          </Link>
          <ThemeToggle />
        </div>
      </header>
      <p className="mb-3 text-xs font-semibold uppercase tracking-widest text-accent">
        Interactive product preview
      </p>
      <h1 className="mb-4 text-3xl font-semibold tracking-tight md:text-4xl">
        Follow an answer back to its evidence.
      </h1>
      <p className="mb-3 max-w-3xl text-ink-secondary">
        Ask a sample question, inspect its citations, browse the library and search the original
        passages.
      </p>
      <p className="mb-8 max-w-3xl text-sm text-ink-secondary">
        Fictional local data. The answer is scripted; no API or model calls are made. This preview
        illustrates the experience while live retrieval is being built.
      </p>
      <div className="mb-5 rounded-panel border border-line bg-surface-0 p-4">
        <strong>Acme workspace</strong>
        <span className="ml-3 text-sm text-ink-secondary">
          Sample member · People and Engineering libraries
        </span>
      </div>
      <nav aria-label="Demo sections" className="mb-6 flex gap-2">
        {["Ask", "Library", "Search"].map((item) => (
          <button
            key={item}
            aria-pressed={view === item}
            onClick={() => {
              setView(item);
              setSelected(null);
            }}
            className="rounded-control border border-control-border px-4 py-2 aria-pressed:bg-accent-soft aria-pressed:text-accent"
          >
            {item}
          </button>
        ))}
      </nav>
      <div className="grid items-start gap-6 min-[1440px]:grid-cols-[minmax(0,1fr)_400px]">
        <section
          aria-label={`${view} workspace`}
          className="rounded-panel border border-line bg-surface-0 p-6"
        >
          <h2 className="mb-5 text-xl font-semibold">
            {view === "Ask"
              ? "Ask your knowledge"
              : view === "Library"
                ? "Knowledge library"
                : "Search passages"}
          </h2>
          {view === "Ask" && (
            <>
              <p className="mb-5 rounded-control border border-line bg-canvas p-4">
                How much parental leave do I get, and how do I request it?
              </p>
              <button
                onClick={() => {
                  setAnswered(true);
                  setSelected(null);
                }}
                className="rounded-control bg-accent px-4 py-2 text-on-accent"
              >
                {answered ? "Replay sample answer" : "Run sample answer"}
              </button>
              {answered && (
                <article className="mt-6 border-t border-line pt-6">
                  <p role="status" className="mb-4 text-sm text-success">
                    Supported by two sample sources
                  </p>
                  <h3 className="mb-3 text-lg font-semibold">16 weeks of paid parental leave</h3>
                  <p className="leading-7">
                    Eligible employees receive 16 weeks of paid leave. Submit your request at least
                    30 days before the expected start date.{" "}
                    <button
                      aria-label="Inspect source S1"
                      onClick={() => setSelected(sources[0])}
                      className="rounded-control bg-accent-soft px-2 text-accent"
                    >
                      [S1]
                    </button>
                  </p>
                  <p className="mt-4 leading-7">
                    Send your proposed dates to your manager and People Operations, who confirms
                    eligibility and records the approved dates.{" "}
                    <button
                      aria-label="Inspect source S2"
                      onClick={() => setSelected(sources[1])}
                      className="rounded-control bg-accent-soft px-2 text-accent"
                    >
                      [S2]
                    </button>
                  </p>
                </article>
              )}
            </>
          )}
          {view === "Search" && (
            <>
              <label htmlFor="passage-search" className="mb-2 block text-sm">
                Search the local sample text
              </label>
              <input
                id="passage-search"
                type="search"
                placeholder="Try leave, manager, or on-call"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                className="mb-5 w-full rounded-control border border-control-border bg-canvas p-3"
              />
              <p role="status" className="text-sm text-ink-secondary">
                {
                  sources.filter((item) =>
                    `${item.title} ${item.text}`.toLowerCase().includes(query.toLowerCase()),
                  ).length
                }{" "}
                sample results
              </p>
            </>
          )}
          {view !== "Ask" && (
            <ul className="divide-y divide-line">
              {sources
                .filter(
                  (item) =>
                    view === "Library" ||
                    `${item.title} ${item.text}`.toLowerCase().includes(query.toLowerCase()),
                )
                .map((item) => (
                  <li key={item.id} className="py-5">
                    <button
                      onClick={() => setSelected(item)}
                      className="text-left font-medium text-accent"
                    >
                      {item.title}
                    </button>
                    <p className="mt-2 text-xs text-ink-secondary">
                      {item.library} · Page {item.page} · Ready
                    </p>
                    {view === "Search" && (
                      <p className="mt-3 text-sm leading-6 text-ink-secondary">{item.text}</p>
                    )}
                  </li>
                ))}
            </ul>
          )}
        </section>
        <aside
          aria-label="Source evidence"
          className="rounded-panel border border-line bg-surface-0 p-6"
        >
          <h2 className="mb-4 text-lg font-semibold">Inspect the evidence</h2>
          {selected ? (
            <>
              <p className="mb-2 text-sm text-accent">
                [{selected.id}] · {selected.library} · Page {selected.page}
              </p>
              <h3 className="mb-4 font-medium">{selected.title}</h3>
              <blockquote className="border-l-2 border-accent bg-accent-soft p-4 text-sm leading-7">
                {selected.text}
              </blockquote>
              <button
                onClick={() => setSelected(null)}
                className="mt-5 rounded-control border border-control-border px-3 py-2 text-sm"
              >
                Close passage
              </button>
            </>
          ) : (
            <>
              <p className="text-sm leading-7 text-ink-secondary">
                Select a citation or a library/search result to reveal its original passage.
              </p>
              <ol className="mt-6 space-y-4 text-sm">
                <li>1. Retrieve permitted evidence.</li>
                <li>2. Answer from those passages.</li>
                <li>3. Verify each claim at its source.</li>
              </ol>
            </>
          )}
        </aside>
      </div>
      <footer className="mt-8 flex gap-5 text-sm">
        <Link className="text-accent" href="/">
          Project overview
        </Link>
        <Link className="text-accent" href="/dev/primitives">
          Explore the design system
        </Link>
      </footer>
    </main>
  );
}
