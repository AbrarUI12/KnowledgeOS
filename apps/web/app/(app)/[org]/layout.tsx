import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { AppShell } from "@/components/shell/app-shell";
import { SessionProviders } from "@/components/shell/session-providers";
import { authenticatedMe } from "@/lib/auth/server";

export default async function OrganizationLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ org: string }>;
}) {
  const { org } = await params;
  const { session, me } = await authenticatedMe();
  if (!me.memberships.some((item) => item.organization_slug === org)) notFound();
  return (
    <SessionProviders key={me.user.id} session={session}>
      <AppShell initialMe={me} organizationSlug={org}>
        {children}
      </AppShell>
    </SessionProviders>
  );
}
