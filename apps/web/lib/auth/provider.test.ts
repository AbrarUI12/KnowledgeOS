import { expect, it } from "vitest";
import { providerConfiguration } from "./provider";
it("keeps local Keycloak defaults", () => {
  expect(providerConfiguration({ OIDC_WEB_CLIENT_SECRET: "secret" }).issuer).toContain(
    "localhost:8080",
  );
});
it("requests an Auth0 API audience and rotating refresh token scope", () => {
  const config = providerConfiguration({
    AUTH_PROVIDER: "auth0",
    AUTH_AUTH0_ID: "client",
    AUTH_AUTH0_SECRET: "secret",
    AUTH_AUTH0_ISSUER: "https://tenant.auth0.com/",
    OIDC_AUDIENCE: "knowledgeos-api",
  });
  expect(config.authorization.params.audience).toBe("knowledgeos-api");
  expect(config.authorization.params.scope).toContain("offline_access");
  expect(config.clientId).toBe("client");
});
it("fails closed on missing Auth0 audience", () => {
  expect(() =>
    providerConfiguration({
      AUTH_PROVIDER: "auth0",
      AUTH_AUTH0_ID: "client",
      AUTH_AUTH0_SECRET: "secret",
      AUTH_AUTH0_ISSUER: "https://tenant.auth0.com/",
    }),
  ).toThrow("OIDC_AUDIENCE");
});
