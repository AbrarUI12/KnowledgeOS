"use client";

import { useEffect, useReducer, useRef, useState } from "react";
import { useSession } from "next-auth/react";
import { useQuery } from "@tanstack/react-query";
import type { components } from "@knowledgeos/contracts";
import { apiClient } from "@/lib/api/client";
import { parseApiError } from "@/lib/api/errors";
import { initialQueryState, queryReducer, readQueryStream } from "@/lib/events/query-stream";
import { Button } from "@/components/primitives/button";
import { Textarea } from "@/components/primitives/textarea";
import { EvidenceRail } from "@/components/shell/evidence-rail";
import { AnswerContent } from "./answer-content";

type Source = components["schemas"]["SourceAlias"];
export function AskWorkspace({
  organizationId,
  userId,
}: {
  organizationId: string;
  userId: string;
}) {
  const { data: session } = useSession();
  const [state, dispatch] = useReducer(queryReducer, initialQueryState);
  const [question, setQuestion] = useState("");
  const [library, setLibrary] = useState("");
  const [selected, setSelected] = useState<Source | null>(null);
  const controller = useRef<AbortController | null>(null);
  const requestId = useRef(0);
  const token = session?.accessToken;
  useEffect(() => () => controller.current?.abort(), []);
  const libraries = useQuery({
    queryKey: ["ask-libraries", organizationId, userId],
    enabled: Boolean(token),
    queryFn: async () => {
      const result = await apiClient(token!, organizationId).GET("/v1/knowledge-bases", {
        params: { header: { "X-Organization-Id": organizationId } },
      });
      if (!result.data) throw parseApiError(result.response.status, result.error);
      return result.data;
    },
  });
  async function submit() {
    const kb = library || libraries.data?.[0]?.id;
    if (!token || !kb || !question.trim() || state.phase === "running") return;
    const id = ++requestId.current;
    controller.current = new AbortController();
    dispatch({ event: "start" });
    setSelected(null);
    try {
      const response = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/v1/knowledge-bases/${encodeURIComponent(kb)}/query/stream`,
        {
          method: "POST",
          credentials: "omit",
          signal: controller.current.signal,
          headers: {
            Authorization: `Bearer ${token}`,
            "X-Organization-Id": organizationId,
            Accept: "text/event-stream",
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ question: question.trim(), scope: {}, filters: {} }),
        },
      );
      await readQueryStream(response, (event) => {
        if (id === requestId.current) dispatch(event);
      });
    } catch (error) {
      if (id !== requestId.current) return;
      if (controller.current?.signal.aborted) dispatch({ event: "cancel" });
      else
        dispatch({
          event: "error",
          data: {
            code: "stream_failed",
            message: error instanceof Error ? error.message : "The answer could not be completed.",
          },
        });
    }
  }
  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="mb-2 text-3xl font-semibold">Ask your knowledge</h1>
      <p className="mb-6 text-ink-secondary">
        Answers use sources you can access in the selected library.
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
        className="space-y-3 rounded-panel border border-line bg-surface-0 p-5"
      >
        <label htmlFor="ask-library" className="block text-sm font-medium">
          Library
        </label>
        <select
          id="ask-library"
          disabled={state.phase === "running"}
          value={library || libraries.data?.[0]?.id || ""}
          onChange={(event) => setLibrary(event.target.value)}
          className="h-control-md w-full rounded-control border border-control-border bg-surface-1 px-3"
        >
          {!libraries.data?.length && (
            <option value="">
              {libraries.isPending ? "Loading libraries…" : "No libraries available"}
            </option>
          )}
          {libraries.data?.map((kb) => (
            <option key={kb.id} value={kb.id}>
              {kb.name}
            </option>
          ))}
        </select>
        {libraries.error && (
          <p role="alert" className="text-danger">
            {libraries.error.message}
          </p>
        )}
        <label htmlFor="ask-question" className="block text-sm font-medium">
          Question
        </label>
        <Textarea
          id="ask-question"
          maxLength={4000}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="What would you like to find out?"
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              void submit();
            }
          }}
        />
        <div className="flex items-center gap-3">
          <Button
            type="submit"
            variant="primary"
            disabled={state.phase === "running" || !question.trim() || !libraries.data?.length}
          >
            Ask
          </Button>
          {state.phase === "running" && (
            <Button type="button" onClick={() => controller.current?.abort()}>
              Cancel
            </Button>
          )}
          <span className="text-xs text-ink-secondary">Shift+Enter for a new line</span>
        </div>
      </form>
      <p role="status" aria-live="polite" className="my-4 text-sm text-ink-secondary">
        {state.phase === "running"
          ? (state.stage?.replaceAll(".", " ") ?? "Starting query…")
          : state.phase === "cancelled"
            ? "Answer cancelled"
            : state.phase === "completed"
              ? "Answer complete"
              : ""}
      </p>
      {state.error && (
        <p role="alert" className="rounded-control bg-danger-soft p-4 text-danger">
          {state.error}
        </p>
      )}
      {state.result?.degraded && (
        <p className="mb-4 rounded-control bg-warning-soft p-4 text-warning">
          Retrieval was degraded. Some sources may be missing.
        </p>
      )}
      {state.result?.abstained && (
        <p className="mb-4 rounded-control border border-line p-4">
          There is not enough evidence to answer. Try another library or rephrase your question.
        </p>
      )}
      {state.text && (
        <article
          aria-label="Answer"
          className="prose-reading rounded-panel border border-line bg-surface-0 p-6"
        >
          <AnswerContent
            text={state.text}
            sources={state.sources}
            citations={state.citations}
            onInspect={setSelected}
          />
        </article>
      )}
      {state.phase === "completed" && state.runId && token && (
        <Feedback token={token} organizationId={organizationId} runId={state.runId} />
      )}
      {selected && token && (
        <EvidenceRail userId={userId} onClose={() => setSelected(null)}>
          <Evidence source={selected} token={token} organizationId={organizationId} />
        </EvidenceRail>
      )}
    </div>
  );
}

function Evidence({
  source,
  token,
  organizationId,
}: {
  source: Source;
  token: string;
  organizationId: string;
}) {
  const [surrounding, setSurrounding] = useState(false);
  const [error, setError] = useState("");
  const context = useQuery({
    queryKey: ["evidence", organizationId, source.chunk_id, surrounding],
    queryFn: async () => {
      const result = await apiClient(token, organizationId).GET("/v1/chunks/{chunk_id}/context", {
        params: {
          header: { "X-Organization-Id": organizationId },
          path: { chunk_id: source.chunk_id },
          query: { before: surrounding ? 1 : 0, after: surrounding ? 1 : 0 },
        },
      });
      if (!result.data) throw parseApiError(result.response.status, result.error);
      return result.data;
    },
  });
  async function openDocument() {
    setError("");
    try {
      const result = await apiClient(token, organizationId).GET(
        "/v1/documents/{document_id}/versions/{version_id}/content-url",
        {
          params: {
            header: { "X-Organization-Id": organizationId },
            path: { document_id: source.document_id, version_id: source.document_version_id },
          },
        },
      );
      if (!result.data) throw parseApiError(result.response.status, result.error);
      const url = new URL(result.data.url);
      if (!["http:", "https:"].includes(url.protocol))
        throw new Error("Source link is unavailable.");
      window.open(url.href, "_blank", "noopener,noreferrer");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Source unavailable.");
    }
  }
  return (
    <div className="space-y-4">
      <h3 className="font-semibold">
        [{source.alias}] {source.title}
      </h3>
      <p className="text-sm text-ink-secondary">
        Version {source.version_number} · {source.section_path.join(" / ")}
        {source.location.page_start ? ` · Page ${source.location.page_start}` : ""}
      </p>
      {context.isPending ? (
        <p role="status">Loading passage…</p>
      ) : context.error ? (
        <p role="alert" className="text-danger">
          Source unavailable: {context.error.message}
        </p>
      ) : (
        <blockquote className="whitespace-pre-wrap border-l-2 border-accent p-3 text-sm">
          {surrounding && context.data?.before?.join("\n\n")}
          {"\n"}
          {context.data?.content}
          {"\n"}
          {surrounding && context.data?.after?.join("\n\n")}
        </blockquote>
      )}
      <label className="flex gap-2 text-sm">
        <input
          type="checkbox"
          checked={surrounding}
          onChange={(event) => setSurrounding(event.target.checked)}
        />{" "}
        Surrounding context
      </label>
      <Button onClick={() => void openDocument()}>Open original document</Button>
      {error && (
        <p role="alert" className="text-danger">
          {error}
        </p>
      )}
    </div>
  );
}
function Feedback({
  token,
  organizationId,
  runId,
}: {
  token: string;
  organizationId: string;
  runId: string;
}) {
  const [status, setStatus] = useState("");
  async function send(rating: "up" | "down") {
    setStatus("Sending…");
    const result = await apiClient(token, organizationId)
      .POST("/v1/query-runs/{query_run_id}/feedback", {
        params: { header: { "X-Organization-Id": organizationId }, path: { query_run_id: runId } },
        body: { rating },
      })
      .catch(() => null);
    setStatus(result?.data ? "Feedback saved" : "Feedback could not be saved. Please retry.");
  }
  return (
    <div className="my-4 flex flex-wrap items-center gap-2">
      <span className="text-sm">Was this helpful?</span>
      <Button disabled={status === "Sending…"} onClick={() => void send("up")}>
        Yes
      </Button>
      <Button disabled={status === "Sending…"} onClick={() => void send("down")}>
        No
      </Button>
      <span role="status" className="text-sm">
        {status}
      </span>
    </div>
  );
}
