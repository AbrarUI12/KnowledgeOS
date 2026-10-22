import { describe, expect, it } from "vitest";
import { initialQueryState, queryReducer, readQueryStream } from "./query-stream";

describe("query stream", () => {
  it("ignores events after cancellation and resets for the next question", () => {
    let state = queryReducer(initialQueryState, { event: "start" });
    state = queryReducer(state, { event: "answer_delta", data: { text: "Partial" } });
    state = queryReducer(state, { event: "cancel" });
    expect(queryReducer(state, { event: "answer_delta", data: { text: "late" } }).text).toBe(
      "Partial",
    );
    expect(queryReducer(state, { event: "start" }).text).toBe("");
  });
  it("handles frames split across byte boundaries and rejects a truncated stream", async () => {
    const encoder = new TextEncoder();
    const response = new Response(
      new ReadableStream({
        start(controller) {
          controller.enqueue(encoder.encode('event: answer_delta\ndata: {"text":"hello"}\n'));
          controller.enqueue(
            encoder.encode('\nevent: error\ndata: {"code":"failed","message":"Unavailable"}\n\n'),
          );
          controller.close();
        },
      }),
      { headers: { "Content-Type": "text/event-stream" } },
    );
    const events: string[] = [];
    await readQueryStream(response, (event) => events.push(event.event));
    expect(events).toEqual(["answer_delta", "error"]);
    await expect(
      readQueryStream(
        new Response('event: answer_delta\ndata: {"text":"partial"}\n\n', {
          headers: { "Content-Type": "text/event-stream" },
        }),
        () => {},
      ),
    ).rejects.toThrow("before completion");
  });
});
