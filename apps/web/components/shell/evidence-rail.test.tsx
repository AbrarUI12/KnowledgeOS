import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { EvidenceRail } from "@/components/shell/evidence-rail";

describe("evidence resize handle", () => {
  it("supports arrows and range endpoints by keyboard", async () => {
    vi.stubGlobal("matchMedia", () => ({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
    localStorage.clear();
    const user = userEvent.setup();
    render(
      <EvidenceRail userId="user-1" onClose={vi.fn()}>
        Evidence content
      </EvidenceRail>,
    );
    const handle = screen.getByRole("separator", { name: "Resize evidence pane" });
    handle.focus();
    await user.keyboard("{ArrowLeft}");
    expect(handle).toHaveAttribute("aria-valuenow", "410");
    await user.keyboard("{End}");
    expect(handle).toHaveAttribute("aria-valuenow", "440");
    await user.keyboard("{Home}");
    expect(handle).toHaveAttribute("aria-valuenow", "360");
    expect(localStorage.getItem("kos:user-1:evidence-width")).toBe("360");
  });
});
