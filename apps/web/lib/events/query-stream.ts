import type { components } from "@knowledgeos/contracts";
import { parseApiError } from "@/lib/api/errors";

export type QueryEvent = components["schemas"]["StreamEvent"];
export type QueryState = {
  phase: "idle" | "running" | "completed" | "failed" | "cancelled";
  text: string;
  sources: components["schemas"]["SourceAlias"][];
  citations: Record<string, boolean>;
  runId?: string;
  stage?: string;
  result?: components["schemas"]["StreamDone"];
  error?: string;
};
export const initialQueryState: QueryState = {
  phase: "idle",
  text: "",
  sources: [],
  citations: {},
};
export function queryReducer(
  state: QueryState,
  action: QueryEvent | { event: "start" | "cancel" },
): QueryState {
  if (action.event === "start") return { ...initialQueryState, phase: "running" };
  if (action.event === "cancel") return { ...state, phase: "cancelled" };
  if (state.phase !== "running") return state;
  switch (action.event) {
    case "meta":
      return { ...state, runId: action.data.query_run_id };
    case "stage":
      return { ...state, stage: action.data.stage };
    case "sources":
      return { ...state, sources: action.data.sources };
    case "answer_delta":
      return { ...state, text: state.text + action.data.text };
    case "citation":
      return {
        ...state,
        citations: { ...state.citations, [action.data.alias]: action.data.valid },
      };
    case "done":
      return { ...state, phase: "completed", result: action.data };
    case "error":
      return { ...state, phase: "failed", error: action.data.message };
  }
}

export async function readQueryStream(response: Response, receive: (event: QueryEvent) => void) {
  if (!response.ok) throw parseApiError(response.status, await response.json().catch(() => null));
  if (!response.headers.get("content-type")?.includes("text/event-stream") || !response.body)
    throw new Error("The server did not return an answer stream.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let terminal = false;
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      buffer = buffer.replace(/\r\n/g, "\n");
      let end: number;
      while ((end = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        const event = frame
          .split("\n")
          .find((line) => line.startsWith("event:"))
          ?.slice(6)
          .trim();
        const payload = frame
          .split("\n")
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trimStart())
          .join("\n");
        if (!event || !payload) continue;
        if (
          !["meta", "stage", "sources", "answer_delta", "citation", "done", "error"].includes(event)
        )
          continue;
        if (terminal) continue;
        receive({ event, data: JSON.parse(payload) } as QueryEvent);
        terminal = event === "done" || event === "error";
      }
      if (terminal) {
        await reader.cancel();
        break;
      }
      if (done) break;
    }
    if (!terminal) throw new Error("The answer stream ended before completion. Please retry.");
  } finally {
    reader.releaseLock();
  }
}
