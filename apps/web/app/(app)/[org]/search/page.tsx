import { notFound } from "next/navigation";
import { authenticatedMe } from "@/lib/auth/server";
import { SearchWorkspace } from "@/features/search/search-workspace";
export default async function Page({ params }: { params: Promise<{ org: string }> }) {
  const { org } = await params;
  const { me } = await authenticatedMe();
  const membership = me.memberships.find((item) => item.organization_slug === org);
  if (!membership || !membership.permissions.includes("query.execute")) notFound();
  return (
    <SearchWorkspace
      organizationId={membership.organization_id}
      canDebug={membership.permissions.includes("retrieval.debug")}
    />
  );
}
