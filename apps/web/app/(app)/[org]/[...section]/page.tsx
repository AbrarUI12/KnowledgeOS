import { notFound } from "next/navigation";
import { navigation } from "@/components/shell/navigation";

export default async function SectionPage({ params }: { params: Promise<{ section: string[] }> }) {
  const { section } = await params;
  const page = navigation.find((item) => item.path === section.join("/"));
  if (!page) notFound();
  return (
    <div className="max-w-reading">
      <p className="mb-3 text-sm text-ink-secondary">Workspace</p>
      <h1 className="mb-4 text-3xl font-semibold">{page.title}</h1>
      <p className="text-ink-secondary">
        Your {page.title.toLowerCase()} workspace will be available here as its features are
        connected.
      </p>
    </div>
  );
}
