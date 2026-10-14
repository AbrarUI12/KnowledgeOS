import { redirect } from "next/navigation";
import { authenticatedMe } from "@/lib/auth/server";

export default async function WorkspacePage() {
  const { me } = await authenticatedMe();
  redirect(me.memberships.length ? `/${me.memberships[0].organization_slug}/home` : "/onboarding");
}
