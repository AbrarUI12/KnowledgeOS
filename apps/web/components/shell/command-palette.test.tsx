import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { CommandPalette } from "./command-palette";

it("opens with Ctrl+K, filters by permissions and text, and closes with Escape", async () => {
  const user = userEvent.setup();
  render(<CommandPalette organizationSlug="acme" permissions={["query.execute"]} />);
  await user.keyboard("{Control>}k{/Control}");
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Ask" })).toHaveAttribute("href", "/acme/ask");
  expect(screen.queryByRole("link", { name: "Members" })).not.toBeInTheDocument();
  await user.type(screen.getByLabelText("Find a page"), "Search");
  expect(screen.getByRole("link", { name: "Search" })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Ask" })).not.toBeInTheDocument();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
