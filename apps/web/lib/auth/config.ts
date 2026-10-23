import NextAuth from "next-auth";

import { refreshAccessToken } from "@/lib/auth/refresh";
import { providerConfiguration } from "@/lib/auth/provider";

export const { handlers, auth, signIn, signOut } = NextAuth(() => {
  const { issuer, clientId, clientSecret, authorization } = providerConfiguration(process.env);
  return {
    session: { strategy: "jwt" },
    pages: { signIn: "/signin", signOut: "/signout", error: "/signin" },
    providers: [
      {
        id: "oidc",
        name: "Organization account",
        type: "oidc",
        issuer,
        clientId,
        clientSecret,
        authorization,
        checks: ["pkce", "state", "nonce"],
      },
    ],
    callbacks: {
      async jwt({ token, account }) {
        if (account)
          return {
            ...token,
            accessToken: account.access_token,
            refreshToken: account.refresh_token,
            accessTokenExpires: account.expires_at,
            error: undefined,
          };
        if (token.error) return token;
        if (token.accessTokenExpires && Date.now() < (token.accessTokenExpires - 30) * 1000)
          return token;
        return refreshAccessToken(token, { issuer, clientId, clientSecret });
      },
      session({ session, token }) {
        session.accessToken = token.error ? undefined : token.accessToken;
        session.accessTokenExpires = token.accessTokenExpires;
        session.error = token.error;
        return session;
      },
    },
  };
});
