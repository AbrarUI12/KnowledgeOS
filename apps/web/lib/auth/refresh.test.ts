import { afterEach, describe, expect, it, vi } from "vitest";
import { refreshAccessToken } from "@/lib/auth/refresh";

afterEach(() => vi.unstubAllGlobals());
const config = { issuer: "https://issuer.test/", clientId: "web", clientSecret: "synthetic" };
describe("refresh rotation", () => {
  it("coalesces concurrent calls and retains the replacement refresh token", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(
        Response.json({ issuer: config.issuer, token_endpoint: "https://issuer.test/token" }),
      )
      .mockResolvedValueOnce(
        Response.json({
          access_token: "access-new",
          expires_in: 300,
          refresh_token: "refresh-new",
        }),
      );
    vi.stubGlobal("fetch", fetcher);
    const token = { refreshToken: "rotation-test-1", accessToken: "expired" };
    const [a, b] = await Promise.all([
      refreshAccessToken(token, config),
      refreshAccessToken(token, config),
    ]);
    expect(a.accessToken).toBe("access-new");
    expect(a.refreshToken).toBe("refresh-new");
    expect(b).toEqual(a);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it("fails closed and clears the access token when discovery issuer differs", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        Response.json({
          issuer: "https://issuer.test",
          token_endpoint: "https://issuer.test/token",
        }),
      ),
    );
    const result = await refreshAccessToken(
      { refreshToken: "rotation-test-2", accessToken: "expired" },
      config,
    );
    expect(result.error).toBe("RefreshTokenError");
    expect(result.accessToken).toBeUndefined();
  });
});
