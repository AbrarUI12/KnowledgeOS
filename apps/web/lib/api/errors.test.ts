import { describe, expect, it } from "vitest";
import { parseApiError } from "@/lib/api/errors";

describe("API error boundary", () => {
  it("preserves a validated server error and request ID", () => {
    const error = parseApiError(403, {
      error: { code: "forbidden", message: "Access denied", request_id: "req-1", details: {} },
    });
    expect(error.status).toBe(403);
    expect(error.code).toBe("forbidden");
    expect(error.requestId).toBe("req-1");
  });
  it.each([null, "<html>internal details</html>", { error: { message: 1 } }])(
    "does not expose malformed upstream responses",
    (body) => {
      expect(parseApiError(500, body).message).toBe("The request could not be completed.");
    },
  );
});
