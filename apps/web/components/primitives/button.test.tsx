import { render, screen } from "@testing-library/react";
import { Settings } from "lucide-react";
import { describe, expect, it } from "vitest";

import { Button, IconButton } from "./button";

describe("Button", () => {
  it("defaults to the secondary variant at the medium control height", () => {
    render(<Button>Save</Button>);
    const button = screen.getByRole("button", { name: "Save" });
    expect(button).toHaveAttribute("data-variant", "secondary");
    expect(button).toHaveAttribute("data-size", "md");
    expect(button.className).toContain("h-control-md");
  });

  it("is not pill-shaped (uses the control radius token)", () => {
    render(<Button variant="primary">Ask</Button>);
    const button = screen.getByRole("button", { name: "Ask" });
    expect(button.className).toContain("rounded-control");
    expect(button.className).not.toContain("rounded-full");
  });

  it("never suppresses the global focus outline", () => {
    render(<Button>Focus me</Button>);
    expect(screen.getByRole("button").className).not.toMatch(/outline-none|outline-hidden/);
  });
});

describe("IconButton", () => {
  it("exposes its aria-label as the accessible name and as a tooltip", () => {
    render(
      <IconButton aria-label="Open settings">
        <Settings aria-hidden="true" />
      </IconButton>,
    );
    const button = screen.getByRole("button", { name: "Open settings" });
    expect(button).toHaveAttribute("title", "Open settings");
    expect(button).toHaveAttribute("data-size", "icon-md");
  });

  it("requires an aria-label at the type level", () => {
    // @ts-expect-error - icon-only buttons must be labelled
    render(<IconButton />);
    expect(screen.getByRole("button")).toBeInTheDocument();
  });
});
