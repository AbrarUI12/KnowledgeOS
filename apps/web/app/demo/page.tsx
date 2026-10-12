import Link from "next/link";

// Placeholder until the interactive demo lands (Codex replaces this file).
export default function DemoPlaceholder() {
  return (
    <main
      id="main-content"
      className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center gap-4 bg-canvas px-4 text-ink sm:px-6"
    >
      <h1 className="text-3xl font-semibold tracking-tight">Interactive demo</h1>
      <p className="text-ink-secondary">
        The interactive walkthrough (ask with streamed, cited answers; knowledge library; search)
        is being published. Check back shortly.
      </p>
      <Link className="text-accent underline-offset-4 hover:underline" href="/">
        Back to the project overview
      </Link>
    </main>
  );
}
