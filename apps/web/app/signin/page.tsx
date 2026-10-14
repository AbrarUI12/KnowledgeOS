import { signIn } from "@/lib/auth/config";
import { Suspense } from "react";

async function SignInForm({
  searchParams,
}: {
  searchParams: Promise<{ callbackUrl?: string; error?: string }>;
}) {
  const params = await searchParams;
  const redirectTo =
    params.callbackUrl?.startsWith("/") && !params.callbackUrl.startsWith("//")
      ? params.callbackUrl
      : "/workspace";
  return (
    <main
      id="main-content"
      className="mx-auto flex min-h-dvh max-w-reading flex-col justify-center gap-5 p-8"
    >
      <p className="text-sm text-ink-secondary">KnowledgeOS</p>
      <h1 className="text-3xl font-semibold">Your organization’s knowledge, with evidence.</h1>
      <p className="text-ink-secondary">Sign in with your organization account to continue.</p>
      {params.error && (
        <p role="alert" className="text-danger">
          Sign-in could not be completed. Please try again.
        </p>
      )}
      <form
        action={async () => {
          "use server";
          await signIn("oidc", { redirectTo });
        }}
      >
        <button className="rounded-control bg-accent px-5 py-3 text-on-accent">Sign in</button>
      </form>
    </main>
  );
}

export default function SignInPage(props: {
  searchParams: Promise<{ callbackUrl?: string; error?: string }>;
}) {
  return (
    <Suspense
      fallback={
        <main id="main-content" className="p-8">
          Loading sign in…
        </main>
      }
    >
      <SignInForm {...props} />
    </Suspense>
  );
}
