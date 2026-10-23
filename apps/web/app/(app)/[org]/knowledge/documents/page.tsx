import { redirect } from "next/navigation";
export default async function Documents({ params }: { params: Promise<{ org: string }> }) {
  const { org } = await params;
  redirect(`/${org}/knowledge/libraries`);
}
