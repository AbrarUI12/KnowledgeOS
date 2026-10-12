import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import DemoWalkthrough from "./page";

vi.mock("@/components/theme-toggle", () => ({ ThemeToggle: () => <button>Theme</button> }));

describe("demo walkthrough", () => {
  it("opens the original passage through an answer citation", async () => {
    const user = userEvent.setup();
    render(<DemoWalkthrough />);
    await user.click(screen.getByRole("button", { name: "Run sample answer" }));
    await user.click(screen.getByRole("button", { name: "Inspect source S1" }));
    expect(screen.getByRole("complementary")).toHaveTextContent("Employee handbook");
    expect(screen.getByRole("complementary")).toHaveTextContent("Page 12");
  });
  it("filters sample passages and reports an empty search", async () => {
    const user = userEvent.setup();
    render(<DemoWalkthrough />);
    await user.click(screen.getByRole("button", { name: "Search", exact: true }));
    await user.type(screen.getByRole("searchbox"), "on-call");
    expect(screen.getByRole("status")).toHaveTextContent("1 sample results");
    expect(screen.getByRole("button", { name: "Engineering runbook" })).toBeInTheDocument();
    await user.clear(screen.getByRole("searchbox"));
    await user.type(screen.getByRole("searchbox"), "no-match");
    expect(screen.getByRole("status")).toHaveTextContent("0 sample results");
  });
  it("inspects library evidence and keeps navigation basePath-neutral", async () => {
    const user = userEvent.setup();
    render(<DemoWalkthrough />);
    await user.click(screen.getByRole("button", { name: "Library" }));
    await user.click(screen.getByRole("button", { name: "Leave request guide" }));
    expect(screen.getByRole("complementary")).toHaveTextContent("Page 3");
    expect(screen.getByRole("link", { name: "Project overview" })).toHaveAttribute("href", "/");
  });
});
