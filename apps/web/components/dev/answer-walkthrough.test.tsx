import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AnswerWalkthrough } from "./answer-walkthrough";

afterEach(() => vi.unstubAllGlobals());
describe("evidence outcomes", () => {
  it("shows an abstention immediately with reduced motion", async () => {
    vi.stubGlobal("matchMedia", () => ({ matches: true }));
    const user = userEvent.setup();
    render(<AnswerWalkthrough inspect={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Insufficient evidence" }));
    await user.click(screen.getByRole("button", { name: "Play outcome" }));
    expect(screen.getByRole("status")).toHaveTextContent("Abstained");
    expect(screen.getByLabelText("Sample answer")).toHaveTextContent("cannot establish");
  });
  it("exposes both conflicting policy sources", async () => {
    vi.stubGlobal("matchMedia", () => ({ matches: true }));
    const inspect = vi.fn();
    const user = userEvent.setup();
    render(<AnswerWalkthrough inspect={inspect} />);
    await user.click(screen.getByRole("button", { name: "Conflicting policies" }));
    await user.click(screen.getByRole("button", { name: "Play outcome" }));
    expect(screen.getByLabelText("Sample answer")).toHaveTextContent("12 weeks");
    expect(screen.getByLabelText("Sample answer")).toHaveTextContent("16 weeks");
    await user.click(screen.getByRole("button", { name: "Inspect [S4]" }));
    expect(inspect).toHaveBeenCalledWith("S4");
  });
});
