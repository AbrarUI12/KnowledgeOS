import { afterEach, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api/client";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

it("uses the repository API default and never sends browser cookies", async () => {
  vi.stubEnv("NEXT_PUBLIC_API_URL", undefined);
  const fetch = vi.fn(async (request: Request) => {
    expect(request).toBeInstanceOf(Request);
    return new Response("{}", { status: 200 });
  });
  vi.stubGlobal("fetch", fetch);
  await apiClient("token", "org").GET("/v1/me");
  const request = fetch.mock.calls[0][0] as Request;
  expect(request.url).toBe("http://localhost:8000/v1/me");
  expect(request.credentials).toBe("omit");
  expect(request.headers.get("Authorization")).toBe("Bearer token");
  expect(request.headers.get("X-Organization-Id")).toBe("org");
});
