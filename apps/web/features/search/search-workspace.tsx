"use client";
import { useState } from "react";
import { useSession } from "next-auth/react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { apiClient } from "@/lib/api/client";
import { parseApiError } from "@/lib/api/errors";
import { Button } from "@/components/primitives/button";
import { Input } from "@/components/primitives/input";
import type { components } from "@knowledgeos/contracts";

export function SearchWorkspace({
  organizationId,
  canDebug,
  initialQuery = "",
  initialLibrary = "",
}: {
  organizationId: string;
  canDebug: boolean;
  initialQuery?: string;
  initialLibrary?: string;
}) {
  const { data: session } = useSession();
  const [query, setQuery] = useState(initialQuery);
  const [kb, setKb] = useState(initialLibrary);
  const [debug, setDebug] = useState(false);
  const [selected, setSelected] = useState<components["schemas"]["SearchHit"] | null>(null);
  const token = session?.accessToken;
  const headers = { "X-Organization-Id": organizationId };
  const libraries = useQuery({
    queryKey: ["search-libraries", organizationId],
    enabled: Boolean(token),
    queryFn: async () => {
      const result = await apiClient(token!, organizationId).GET("/v1/knowledge-bases", {
        params: { header: headers },
      });
      if (!result.data) throw parseApiError(result.response.status, result.error);
      return result.data;
    },
  });
  const search = useMutation({
    mutationFn: async () => {
      const result = await apiClient(token!, organizationId).POST(
        "/v1/knowledge-bases/{kb_id}/search",
        {
          params: { header: headers, path: { kb_id: kb || libraries.data![0].id } },
          body: {
            query: query.trim(),
            debug: canDebug && debug,
            filters: {
              document_ids: [],
              document_types: [],
              languages: [],
              source_ids: [],
              tags: [],
            },
            limit: 20,
          },
        },
      );
      if (!result.data) throw parseApiError(result.response.status, result.error);
      return result.data;
    },
  });
  const context = useQuery({
    queryKey: ["search-context", organizationId, selected?.chunk_id],
    enabled: Boolean(token && selected),
    queryFn: async () => {
      const result = await apiClient(token!, organizationId).GET("/v1/chunks/{chunk_id}/context", {
        params: {
          header: headers,
          path: { chunk_id: selected!.chunk_id },
          query: { before: 1, after: 1 },
        },
      });
      if (!result.data) throw parseApiError(result.response.status, result.error);
      return result.data;
    },
  });
  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <h1 className="text-3xl font-semibold">Search knowledge</h1>
      <p className="text-ink-secondary">
        Find exact terms and related passages in sources you can access.
      </p>
      <form
        className="flex flex-wrap gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          setSelected(null);
          if (query.trim() && libraries.data?.length) {
            const url = new URL(window.location.href);
            url.searchParams.set("q", query.trim());
            url.searchParams.set("kb", kb || libraries.data[0].id);
            window.history.replaceState(null, "", url);
            search.mutate();
          }
        }}
      >
        <select
          aria-label="Library"
          value={kb || libraries.data?.[0]?.id || ""}
          onChange={(event) => setKb(event.target.value)}
          className="rounded-control border border-control-border bg-surface-1 p-2"
        >
          {!libraries.data?.length && <option>No libraries available</option>}
          {libraries.data?.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
        <Input
          className="flex-1"
          aria-label="Search query"
          maxLength={2000}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Policy code, phrase, or question"
        />
        <Button
          variant="primary"
          disabled={search.isPending || !query.trim() || !libraries.data?.length}
          type="submit"
        >
          Search
        </Button>
        {canDebug && (
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={debug}
              onChange={(event) => setDebug(event.target.checked)}
            />{" "}
            Retrieval debugger
          </label>
        )}
      </form>
      {(libraries.error || search.error) && (
        <p role="alert" className="rounded-control bg-danger-soft p-4 text-danger">
          {(libraries.error || search.error)?.message}
        </p>
      )}
      {search.isPending && <p role="status">Searching permitted sources…</p>}
      {search.data && (
        <>
          <p role="status" className="text-sm text-ink-secondary">
            {search.data.hits.length} results
            {search.data.degraded ? " · Retrieval degraded: some sources may be missing" : ""}
          </p>
          <ul
            className="divide-y divide-line rounded-panel border border-line bg-surface-0"
            onKeyDown={(event) => {
              if (!["ArrowDown", "ArrowUp"].includes(event.key)) return;
              const buttons = Array.from(
                event.currentTarget.querySelectorAll<HTMLButtonElement>("button"),
              );
              if (!buttons.length) return;
              event.preventDefault();
              const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
              buttons[
                (index + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length
              ].focus();
            }}
          >
            {search.data.hits.map((hit) => (
              <li key={hit.chunk_id} className="p-5">
                <button
                  onClick={() => setSelected(hit)}
                  className="font-semibold text-accent hover:underline"
                >
                  {hit.title}
                </button>
                <p className="my-1 text-xs text-ink-secondary">
                  {hit.match_type} match · {hit.section_path.join(" / ")}
                  {hit.location.page_start ? ` · Page ${hit.location.page_start}` : ""}
                </p>
                <p className="text-sm leading-6">
                  {hit.snippet.split(/(«[^»]*»)/g).map((part, index) =>
                    part.startsWith("«") ? (
                      <mark key={index} className="bg-accent-soft text-ink">
                        {part.slice(1, -1)}
                      </mark>
                    ) : (
                      part
                    ),
                  )}
                </p>
              </li>
            ))}
            {search.data.hits.length === 0 && (
              <li className="p-6">
                No matching passages. Try a broader phrase or another library.
              </li>
            )}
          </ul>
        </>
      )}
      {selected && (
        <section
          aria-label="Passage preview"
          className="rounded-panel border border-line bg-surface-0 p-5"
        >
          <div className="mb-3 flex justify-between">
            <h2 className="font-semibold">{selected.title}</h2>
            <Button onClick={() => setSelected(null)}>Close preview</Button>
          </div>
          {context.isPending ? (
            <p role="status">Loading passage…</p>
          ) : context.error ? (
            <p role="alert" className="text-danger">
              {context.error.message}
            </p>
          ) : (
            <blockquote className="whitespace-pre-wrap border-l-2 border-accent p-4">
              {context.data?.content}
            </blockquote>
          )}
        </section>
      )}
      {canDebug && search.data?.debug && (
        <section
          aria-label="Retrieval debugger"
          className="overflow-x-auto rounded-panel border border-line bg-surface-0 p-5"
        >
          <h2 className="mb-3 font-semibold">Retrieval debugger</h2>
          <p className="mb-3 text-sm text-ink-secondary">
            {search.data.debug.principal_summary} · {search.data.debug.embedding_model} ·{" "}
            {search.data.debug.rag_profile_version}
          </p>
          <table className="w-full text-left text-sm">
            <thead>
              <tr>
                {[
                  "Source",
                  "Dense rank",
                  "Lexical rank",
                  "Fused score",
                  "Rerank score",
                  "Context",
                ].map((title) => (
                  <th key={title} className="border-b border-line p-2">
                    {title}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {search.data.debug.hits.map((hit) => (
                <tr key={hit.chunk_id}>
                  {[
                    hit.title,
                    hit.dense_rank,
                    hit.lexical_rank,
                    hit.fused_score?.toFixed(4),
                    hit.rerank_score?.toFixed(4),
                    hit.selected_for_context ? "Selected" : "—",
                  ].map((value, index) => (
                    <td key={index} className="border-b border-line p-2">
                      {value ?? "—"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-3 font-mono text-xs">Run {search.data.query_run_id}</p>
        </section>
      )}
    </div>
  );
}
