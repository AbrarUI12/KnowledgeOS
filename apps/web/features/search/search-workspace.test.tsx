import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { SearchWorkspace } from "./search-workspace";
vi.mock("next-auth/react", () => ({ useSession: () => ({ data: { accessToken: "test-token" } }) }));
afterEach(() => vi.unstubAllGlobals());
it("searches and previews permitted passages without exposing debug controls to members", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (request: Request) => {
      if (request.url.includes("/context"))
        return Response.json({ content: "Exact original passage", before: [], after: [] });
      if (request.method === "POST")
        return Response.json({
          query_run_id: "run",
          hits: [
            {
              chunk_id: "chunk",
              title: "Policy",
              section_path: [],
              location: {},
              snippet: "Policy «HR-142-B»",
              match_type: "exact",
            },
          ],
          degraded: false,
        });
      return Response.json([{ id: "kb", name: "People" }]);
    }),
  );
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <SearchWorkspace organizationId="org" canDebug={false} />
    </QueryClientProvider>,
  );
  await screen.findByRole("option", { name: "People" });
  expect(screen.queryByLabelText("Retrieval debugger")).not.toBeInTheDocument();
  await user.type(screen.getByLabelText("Search query"), "HR-142-B");
  await user.click(screen.getByRole("button", { name: /^Search$/ }));
  await user.click(await screen.findByRole("button", { name: "Policy" }));
  expect(await screen.findByText("Exact original passage")).toBeInTheDocument();
});
