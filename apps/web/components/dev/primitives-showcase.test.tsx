import { render, screen } from "@testing-library/react";
import axe from "axe-core";
import { describe, expect, it } from "vitest";

import { Providers } from "@/components/providers";

import { PrimitivesShowcase } from "./primitives-showcase";

describe("PrimitivesShowcase", () => {
  it("renders every primitive section", () => {
    render(
      <Providers>
        <PrimitivesShowcase />
      </Providers>,
    );
    for (const section of [
      "Typography",
      "Buttons",
      "Form controls",
      "Status",
      "Tabs",
      "Overlays",
    ]) {
      expect(screen.getByRole("heading", { name: section })).toBeInTheDocument();
    }
  });

  it("has no automatically detectable accessibility violations", async () => {
    const { container } = render(
      <Providers>
        <main>
          <PrimitivesShowcase />
        </main>
      </Providers>,
    );

    const results = await axe.run(container, {
      // jsdom has no layout engine, so color contrast is verified in tests/contrast.test.ts instead.
      rules: { "color-contrast": { enabled: false } },
    });

    const summary = results.violations.map(
      (v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`,
    );
    expect(summary).toEqual([]);
  });
});
