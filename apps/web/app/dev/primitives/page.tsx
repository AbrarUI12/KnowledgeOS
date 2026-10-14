import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { PrimitivesShowcase } from "@/components/dev/primitives-showcase";

export const metadata: Metadata = { title: "Primitives", robots: { index: false } };

/** Design-system preview: public in the static showcase, opt-in in the production app. */
export default function PrimitivesPage() {
  if (
    process.env.NODE_ENV === "production" &&
    process.env.ENABLE_DEV_ROUTES !== "true" &&
    process.env.KOS_STATIC_EXPORT !== "1"
  ) {
    notFound();
  }
  return (
    <main id="main-content" className="mx-auto w-full max-w-5xl px-6 py-10">
      <PrimitivesShowcase />
    </main>
  );
}
