import { notFound } from "next/navigation";

import { KnowledgeLibrary } from "@/features/knowledge/knowledge-library";
import { authenticatedMe } from "@/lib/auth/server";

export default async function KnowledgeLibraryPage({
  params,
}: {
  params: Promise<{ org: string }>;
}) {
  const { org } = await params;
  const { me } = await authenticatedMe();
  const membership = me.memberships.find((item) => item.organization_slug === org);
  if (!membership) notFound();

  return (
    <KnowledgeLibrary
      organizationId={membership.organization_id}
      capabilities={{
        createLibrary: membership.permissions.includes("kb.create"),
        upload: membership.permissions.includes("document.upload"),
        publish: membership.permissions.includes("document.publish"),
      }}
    />
  );
}
