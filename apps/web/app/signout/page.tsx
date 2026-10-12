import { signOut } from "@/lib/auth/config";

export default function SignOutPage() {
  return (
    <main
      id="main-content"
      className="mx-auto flex min-h-dvh max-w-reading flex-col justify-center gap-5 p-8"
    >
      <h1 className="text-3xl font-semibold">Sign out of KnowledgeOS?</h1>
      <form
        action={async () => {
          "use server";
          await signOut({ redirectTo: "/signin" });
        }}
      >
        <button className="rounded-control bg-accent px-5 py-3 text-on-accent">Sign out</button>
      </form>
    </main>
  );
}
