import { getToken } from "next-auth/jwt";
import { NextResponse, type NextRequest } from "next/server";

// Proxy only checks the encrypted session. Layouts and the API perform authoritative checks.
export async function proxy(request: NextRequest) {
  const token = await getToken({
    req: request,
    secret: process.env.AUTH_SECRET,
    secureCookie: request.nextUrl.protocol === "https:",
  });
  if (!token || token.error) {
    const target = new URL("/signin", request.url);
    target.searchParams.set("callbackUrl", request.nextUrl.pathname + request.nextUrl.search);
    return NextResponse.redirect(target);
  }
  return NextResponse.next();
}

export const config = {
  matcher: [
    "/onboarding",
    "/workspace",
    "/((?!api|signin|signout|dev|_next|favicon.ico)[^/]+)/:path*",
  ],
};
