export function providerConfiguration(env: Record<string, string | undefined>) {
  const provider = env.AUTH_PROVIDER ?? "keycloak";
  if (provider !== "keycloak" && provider !== "auth0") throw new Error("Unsupported AUTH_PROVIDER");
  const auth0 = provider === "auth0";
  const issuer = auth0
    ? env.AUTH_AUTH0_ISSUER
    : (env.OIDC_ISSUER ?? "http://localhost:8080/realms/knowledgeos");
  const clientId = auth0 ? env.AUTH_AUTH0_ID : (env.OIDC_WEB_CLIENT_ID ?? "knowledgeos-web");
  const clientSecret = auth0 ? env.AUTH_AUTH0_SECRET : env.OIDC_WEB_CLIENT_SECRET;
  if (!issuer || !clientId || !clientSecret)
    throw new Error("OIDC issuer, client ID and client secret must be configured");
  if (auth0 && !env.OIDC_AUDIENCE) throw new Error("OIDC_AUDIENCE must be configured for Auth0");
  if (auth0 && new URL(issuer).protocol !== "https:")
    throw new Error("Auth0 issuer must use HTTPS");
  return {
    issuer,
    clientId,
    clientSecret,
    authorization: {
      params: {
        scope: auth0 ? "openid profile email offline_access" : "openid profile email",
        ...(auth0 ? { audience: env.OIDC_AUDIENCE! } : {}),
      },
    },
  };
}
