"use client";

import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { useRef, useState, type FormEvent } from "react";

import { apiClient } from "@/lib/api/client";
import { parseApiError } from "@/lib/api/errors";

export function Onboarding() {
  const { data: session } = useSession();
  const router = useRouter();
  const key = useRef<string | null>(null);
  const lastBody = useRef<string | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session?.accessToken || pending) return;
    const form = new FormData(event.currentTarget);
    const body = { name: String(form.get("name")), slug: String(form.get("slug")) };
    const serialized = JSON.stringify(body);
    if (lastBody.current !== serialized) {
      key.current = crypto.randomUUID();
      lastBody.current = serialized;
    }
    setPending(true);
    setError("");
    try {
      const result = await apiClient(session.accessToken).POST("/v1/organizations", {
        body,
        params: { header: { "Idempotency-Key": key.current! } },
      });
      if (!result.data) throw parseApiError(result.response.status, result.error);
      router.push(`/${result.data.slug}/home`);
      router.refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not create the organization.");
    } finally {
      setPending(false);
    }
  }
  return (
    <main id="main-content" className="mx-auto max-w-reading p-8">
      <h1 className="mb-3 text-3xl font-semibold">Create your organization</h1>
      <p className="mb-8 text-ink-secondary">Start a workspace for your team’s knowledge.</p>
      <form onSubmit={submit} className="flex max-w-md flex-col gap-4">
        <label>
          Organization name
          <input
            name="name"
            required
            maxLength={200}
            className="mt-2 block w-full rounded-control border border-control-border bg-surface-0 p-3"
          />
        </label>
        <label>
          URL slug
          <input
            name="slug"
            required
            maxLength={63}
            pattern="[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?"
            className="mt-2 block w-full rounded-control border border-control-border bg-surface-0 p-3"
          />
        </label>
        <p className="text-sm text-ink-secondary">Use lowercase letters, numbers and hyphens.</p>
        {error && (
          <p role="alert" className="text-danger">
            {error}
          </p>
        )}
        <button
          disabled={pending || !session?.accessToken}
          className="rounded-control bg-accent px-4 py-3 text-on-accent disabled:opacity-50"
        >
          {pending ? "Creating…" : "Create organization"}
        </button>
      </form>
    </main>
  );
}
