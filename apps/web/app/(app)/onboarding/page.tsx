import { redirect } from "next/navigation";
import { Onboarding } from "@/components/shell/onboarding";
import { SessionProviders } from "@/components/shell/session-providers";
import { authenticatedMe } from "@/lib/auth/server";

export default async function OnboardingPage() {
  const { session, me } = await authenticatedMe();
  if (me.memberships.length) redirect(`/${me.memberships[0].organization_slug}/home`);
  return (
    <SessionProviders session={session}>
      <Onboarding />
    </SessionProviders>
  );
}
