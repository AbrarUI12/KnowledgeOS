import { notFound } from "next/navigation";
import { authenticatedMe } from "@/lib/auth/server";
import { GroupsPage } from "@/features/access/groups";
export default async function Page({ params }: { params: Promise<{ org: string }> }) {
  const { org } = await params;
  const { me } = await authenticatedMe();
  const membership = me.memberships.find((item) => item.organization_slug === org);
  if (!membership) notFound();
  return (
    <GroupsPage
      organizationId={membership.organization_id}
      canManage={membership.permissions.includes("groups.manage")}
    />
  );
}
