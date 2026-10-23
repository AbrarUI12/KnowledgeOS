import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { MembersPage } from "./members";

vi.mock("next-auth/react", () => ({ useSession: () => ({ data: { accessToken: "test-token" } }) }));
afterEach(() => vi.unstubAllGlobals());

it("updates another member's role and creates a copyable invitation", async () => {
  const requests: Request[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (request: Request) => {
      requests.push(request);
      if (request.method === "PATCH") return Response.json({ user_id: "other", role: "viewer" });
      if (request.method === "POST")
        return Response.json({
          id: "invite",
          email: "new@example.com",
          role: "member",
          expires_at: "2026-11-01T00:00:00Z",
          accept_url: "https://example.com/invite/token",
        });
      return Response.json({
        items: [
          {
            user_id: "self",
            display_name: "Alice",
            email: "alice@example.com",
            role: "owner",
            group_ids: [],
          },
          {
            user_id: "other",
            display_name: "Bob",
            email: "bob@example.com",
            role: "member",
            group_ids: [],
          },
        ],
        next_cursor: null,
      });
    }),
  );
  const user = userEvent.setup();
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MembersPage organizationId="org" currentUserId="self" canManage />
    </QueryClientProvider>,
  );
  await user.selectOptions(await screen.findByLabelText("Role of Bob"), "viewer");
  await waitFor(() => expect(requests.some((request) => request.method === "PATCH")).toBe(true));
  expect(await requests.find((request) => request.method === "PATCH")!.json()).toEqual({
    role: "viewer",
  });
  expect(screen.queryByLabelText("Role of Alice")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /^Invite$/ }));
  await user.type(screen.getByLabelText("Email"), "new@example.com");
  await user.click(screen.getByRole("button", { name: "Create invitation" }));
  expect(await screen.findByLabelText("Invitation link")).toHaveValue(
    "https://example.com/invite/token",
  );
});
