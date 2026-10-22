import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { AskWorkspace } from "./ask-workspace";

vi.mock("next-auth/react", () => ({ useSession: () => ({ data: { accessToken: "test-token" } }) }));
vi.mock("@/components/shell/evidence-rail", () => ({
  EvidenceRail: ({ children }: { children: React.ReactNode }) => (
    <aside aria-label="Evidence">{children}</aside>
  ),
}));

afterEach(() => vi.unstubAllGlobals());

it("streams an answer, renders untrusted markup inertly, and opens its cited passage", async () => {
  const source = {
    alias: "S1",
    chunk_id: "chunk",
    document_id: "doc",
    document_version_id: "version",
    title: "Handbook",
    version_number: 1,
    location: { page_start: 3 },
    section_path: ["Leave"],
    content_hash: "hash",
  };
  const fetchMock = vi.fn(async (request: RequestInfo | URL) => {
    const url = request instanceof Request ? request.url : String(request);
    if (url.endsWith("/knowledge-bases")) return Response.json([{ id: "kb", name: "People" }]);
    if (url.includes("/context"))
      return Response.json({ content: "Sixteen weeks of leave.", before: [], after: [] });
    const events = [
      ["meta", { query_run_id: "run" }],
      ["sources", { sources: [source] }],
      ["answer_delta", { text: 'Sixteen weeks [S1]. <img src="https://bad.example/pixel">' }],
      ["citation", { alias: "S1", valid: true }],
      [
        "done",
        {
          abstained: false,
          evidence_status: "strong",
          degraded: false,
          conflicts: [],
          usage: {},
          timing: {},
        },
      ],
    ];
    return new Response(
      events.map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join(""),
      { headers: { "Content-Type": "text/event-stream" } },
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const user = userEvent.setup();
  const view = render(
    <QueryClientProvider client={client}>
      <AskWorkspace organizationId="org" userId="user" />
    </QueryClientProvider>,
  );
  await screen.findByRole("option", { name: "People" });
  await user.type(screen.getByLabelText("Question"), "How much leave?");
  await user.click(screen.getByRole("button", { name: "Ask", exact: true }));
  await screen.findByText("Answer complete");
  expect(view.container.querySelector("img")).toBeNull();
  await user.click(screen.getByRole("button", { name: "Inspect source S1" }));
  await screen.findByText("Sixteen weeks of leave.");
  await waitFor(() => expect(fetchMock).toHaveBeenCalled());
});
