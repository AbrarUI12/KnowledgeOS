import { describe, expect, it } from "vitest";

import { ingestionLabel, ingestionStatus, isActiveIngestionState } from "./status";

describe("ingestion status mapping", () => {
  it("distinguishes active, review, ready, and failed states", () => {
    expect(isActiveIngestionState("PARSING")).toBe(true);
    expect(isActiveIngestionState("READY")).toBe(false);
    expect(ingestionStatus("PARSING")).toBe("progress");
    expect(ingestionStatus("PENDING_APPROVAL")).toBe("warning");
    expect(ingestionStatus("READY")).toBe("success");
    expect(ingestionStatus("FAILED_RETRYABLE")).toBe("danger");
  });

  it("formats API states for people", () => {
    expect(ingestionLabel("PENDING_APPROVAL")).toBe("Pending Approval");
    expect(ingestionLabel(null)).toBe("Not started");
  });
});
