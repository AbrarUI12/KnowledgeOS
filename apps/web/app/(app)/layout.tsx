import { Suspense, type ReactNode } from "react";

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <Suspense
      fallback={
        <main id="main-content" className="p-8" aria-busy="true">
          Loading your workspace…
        </main>
      }
    >
      {children}
    </Suspense>
  );
}
