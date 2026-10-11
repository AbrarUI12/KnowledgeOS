import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { PrimitivesShowcase } from "@/components/dev/primitives-showcase";

export const metadata: Metadata = { title: "Primitives", robots: { index: false } };

/** Development-only design-system preview. Disabled in production unless explicitly enabled. */
export default function PrimitivesPage() {
  if (process.env.NODE_ENV === "production" && process.env.ENABLE_DEV_ROUTES !== "true") {
    notFound();
  }
  return (
    <main id="main-content" className="mx-auto w-full max-w-5xl px-6 py-10">
      <PrimitivesShowcase />
    </main>
  );
}
