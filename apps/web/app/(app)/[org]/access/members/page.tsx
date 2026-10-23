import { notFound } from "next/navigation";
import { authenticatedMe } from "@/lib/auth/server";
import { MembersPage } from "@/features/access/members";

export default async function Page({ params }: { params: Promise<{ org: string }> }) {
  const { org } = await params;
  const { me } = await authenticatedMe();
  const membership = me.memberships.find((item) => item.organization_slug === org);
  if (!membership) notFound();
  return (
    <MembersPage
      organizationId={membership.organization_id}
      currentUserId={me.user.id}
      canManage={membership.permissions.includes("members.manage")}
    />
  );
}
