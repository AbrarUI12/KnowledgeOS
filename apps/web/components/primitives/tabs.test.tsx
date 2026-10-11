import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "./tabs";

function Example() {
  return (
    <Tabs defaultValue="answer">
      <TabsList aria-label="Result view">
        <TabsTrigger value="answer">Answer</TabsTrigger>
        <TabsTrigger value="sources">Sources</TabsTrigger>
        <TabsTrigger value="trace">Trace</TabsTrigger>
      </TabsList>
      <TabsContent value="answer">Answer panel</TabsContent>
      <TabsContent value="sources">Sources panel</TabsContent>
      <TabsContent value="trace">Trace panel</TabsContent>
    </Tabs>
  );
}

describe("Tabs", () => {
  it("supports arrow-key navigation between triggers", async () => {
    const user = userEvent.setup();
    render(<Example />);

    await user.tab();
    expect(screen.getByRole("tab", { name: "Answer" })).toHaveFocus();

    await user.keyboard("{ArrowRight}");
    const sources = screen.getByRole("tab", { name: "Sources" });
    expect(sources).toHaveFocus();
    expect(sources).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel")).toHaveTextContent("Sources panel");

    await user.keyboard("{End}");
    expect(screen.getByRole("tab", { name: "Trace" })).toHaveAttribute("aria-selected", "true");
  });

  it("renders exactly one active indicator, inside the selected trigger", async () => {
    const user = userEvent.setup();
    const { container } = render(<Example />);

    await user.click(screen.getByRole("tab", { name: "Trace" }));

    const indicators = container.querySelectorAll('[aria-hidden="true"].absolute');
    expect(indicators).toHaveLength(1);
    expect(screen.getByRole("tab", { name: "Trace" })).toContainElement(
      indicators[0] as HTMLElement,
    );
  });
});
