import { z } from "zod";
import type { JWT } from "next-auth/jwt";

const discoverySchema = z.object({ issuer: z.string(), token_endpoint: z.string().url() });
const tokensSchema = z.object({
  access_token: z.string().min(1),
  expires_in: z.number().positive(),
  refresh_token: z.string().min(1).optional(),
});

type RefreshConfig = { issuer: string; clientId: string; clientSecret: string };

// Coalesce concurrent rotations on this server. Briefly retain the result so requests carrying
// the pre-rotation cookie receive the same replacement instead of consuming the token twice.
const rotations = new Map<string, { promise: Promise<JWT>; expires: number }>();

export async function refreshAccessToken(token: JWT, config: RefreshConfig): Promise<JWT> {
  if (!token.refreshToken) return { ...token, accessToken: undefined, error: "RefreshTokenError" };
  const now = Date.now();
  for (const [key, entry] of rotations) if (entry.expires < now) rotations.delete(key);
  const key = token.refreshToken;
  const existing = rotations.get(key);
  if (existing) return { ...token, ...(await existing.promise) };
  const promise = rotate(token, config);
  rotations.set(key, { promise, expires: now + 30_000 });
  return promise;
}

async function rotate(token: JWT, config: RefreshConfig): Promise<JWT> {
  try {
    const discoveryResponse = await fetch(
      `${config.issuer.replace(/\/$/, "")}/.well-known/openid-configuration`,
      { cache: "no-store", signal: AbortSignal.timeout(5_000) },
    );
    if (!discoveryResponse.ok) throw new Error("Discovery unavailable");
    const discovery = discoverySchema.parse(await discoveryResponse.json());
    if (discovery.issuer !== config.issuer) throw new Error("Issuer mismatch");
    const response = await fetch(discovery.token_endpoint, {
      method: "POST",
      cache: "no-store",
      signal: AbortSignal.timeout(5_000),
      body: new URLSearchParams({
        grant_type: "refresh_token",
        refresh_token: token.refreshToken!,
        client_id: config.clientId,
        client_secret: config.clientSecret,
      }),
    });
    if (!response.ok) throw new Error("Refresh rejected");
    const tokens = tokensSchema.parse(await response.json());
    return {
      ...token,
      accessToken: tokens.access_token,
      accessTokenExpires: Math.floor(Date.now() / 1000) + tokens.expires_in,
      refreshToken: tokens.refresh_token ?? token.refreshToken,
      error: undefined,
    };
  } catch {
    return { ...token, accessToken: undefined, error: "RefreshTokenError" };
  }
}
