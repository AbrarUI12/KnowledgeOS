import { redirect } from "next/navigation";

import { getMe } from "@/lib/api/client";
import { auth } from "@/lib/auth/config";

export async function authenticatedMe() {
  const session = await auth();
  if (!session?.accessToken || session.error) redirect("/signin");
  return { session, me: await getMe(session.accessToken) };
}
