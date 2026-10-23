import Link from "next/link";
import { notFound } from "next/navigation";
import { authenticatedMe } from "@/lib/auth/server";

export default async function Home({ params }: { params: Promise<{ org: string }> }) {
  const { org } = await params;
  const { me } = await authenticatedMe();
  const membership = me.memberships.find((item) => item.organization_slug === org);
  if (!membership) notFound();
  const query = membership.permissions.includes("query.execute");
  return (
    <div className="mx-auto max-w-5xl">
      <p className="mb-2 text-sm text-ink-secondary">{membership.organization_name}</p>
      <h1 className="text-3xl font-semibold">Your knowledge workspace</h1>
      <p className="mt-3 max-w-2xl text-ink-secondary">
        Find a source, ask a question, and follow the answer back to its evidence.
      </p>
      {query && (
        <nav
          aria-label="Get started"
          className="mt-8 divide-y divide-line rounded-panel border border-line bg-surface-0"
        >
          {[
            {
              path: "ask",
              title: "Ask your knowledge",
              description: "Get answers grounded in the sources you can access.",
            },
            {
              path: "search",
              title: "Search passages",
              description: "Find exact terms and related passages without generating an answer.",
            },
            {
              path: "knowledge/libraries",
              title: "Browse libraries",
              description: "Explore documents and follow ingestion progress.",
            },
          ].map((item) => (
            <Link
              key={item.path}
              href={`/${org}/${item.path}`}
              className="block p-5 hover:bg-surface-2"
            >
              <h2 className="font-semibold text-accent">{item.title}</h2>
              <p className="mt-1 text-sm text-ink-secondary">{item.description}</p>
            </Link>
          ))}
        </nav>
      )}
      {!query && (
        <Link
          className="mt-8 block rounded-panel border border-line bg-surface-0 p-5 text-accent"
          href={`/${org}/knowledge/libraries`}
        >
          Browse libraries
        </Link>
      )}
    </div>
  );
}
