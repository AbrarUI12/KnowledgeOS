import { notFound } from "next/navigation";
import { authenticatedMe } from "@/lib/auth/server";
import { AskWorkspace } from "@/features/ask/ask-workspace";

export default async function AskPage({ params }: { params: Promise<{ org: string }> }) {
  const { org } = await params;
  const { me } = await authenticatedMe();
  const membership = me.memberships.find((item) => item.organization_slug === org);
  if (!membership || !membership.permissions.includes("query.execute")) notFound();
  return (
    <AskWorkspace
      key={membership.organization_id}
      organizationId={membership.organization_id}
      userId={me.user.id}
    />
  );
}
