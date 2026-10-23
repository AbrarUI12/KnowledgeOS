# Vercel authentication

Set `AUTH_PROVIDER=auth0`, `AUTH_AUTH0_ID`, `AUTH_AUTH0_SECRET`, and
`AUTH_AUTH0_ISSUER` (the HTTPS tenant issuer, including its trailing slash).
Set `OIDC_AUDIENCE` to the API identifier configured on the backend.

Register `https://<web-domain>/api/auth/callback/oidc` as the Auth0 callback URL.
The provider keeps the `oidc` ID so existing sign-in and refresh flows work unchanged.
Enable refresh-token rotation and offline access for the Auth0 application/API.

Set `AUTH_URL` to the web origin, generate `AUTH_SECRET`, and set
`NEXT_PUBLIC_API_URL` to the public HTTPS Space origin before building on Vercel.
The backend CORS allowlist and B2 CORS rules must allow this exact web origin.
Only `NEXT_PUBLIC_API_URL` is public; client secrets must remain server-side.
