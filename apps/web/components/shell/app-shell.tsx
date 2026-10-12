"use client";

import { useQuery } from "@tanstack/react-query";
import { Bell, Menu, PanelRight, Search } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { useTheme } from "next-themes";
import { useRef, useState, type ReactNode } from "react";

import { EvidenceRail } from "@/components/shell/evidence-rail";
import { navigation } from "@/components/shell/navigation";
import { usePreference } from "@/components/shell/use-preference";
import { getMe, queryKeys, type Me } from "@/lib/api/client";
import { hasPermission } from "@/lib/permissions";

export function AppShell({
  initialMe,
  organizationSlug,
  children,
}: {
  initialMe: Me;
  organizationSlug: string;
  children: ReactNode;
}) {
  const { data: session } = useSession();
  const { data: me = initialMe } = useQuery({
    queryKey: queryKeys.me(initialMe.user.id),
    initialData: initialMe,
    queryFn: () => getMe(session!.accessToken!),
    enabled: Boolean(session?.accessToken),
  });
  const membership = me.memberships.find((item) => item.organization_slug === organizationSlug);
  const pathname = usePathname();
  const router = useRouter();
  const { setTheme } = useTheme();
  const [savedCollapsed, saveCollapsed] = usePreference(`kos:${me.user.id}:nav-collapsed`, "false");
  const collapsed = savedCollapsed === "true";
  const [evidence, setEvidence] = useState(false);
  const railTrigger = useRef<HTMLButtonElement>(null);
  if (session?.error)
    return (
      <main id="main-content" className="p-8">
        <h1>Session expired</h1>
        <Link href="/signin">Sign in again</Link>
      </main>
    );
  if (!membership)
    return (
      <main id="main-content" className="p-8">
        <h1>Organization not found</h1>
        <Link href="/workspace">Choose your organization</Link>
      </main>
    );
  return (
    <div className="flex h-dvh flex-col bg-canvas">
      <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-line bg-surface-0 px-4">
        <label className="flex items-center gap-3">
          <span className="hidden font-semibold sm:inline">KnowledgeOS</span>
          <span className="sr-only">Organization</span>
          <select
            className="max-w-48 rounded-control border border-control-border bg-surface-0 p-2 text-sm"
            value={organizationSlug}
            onChange={(event) => router.push(`/${event.target.value}/home`)}
          >
            {me.memberships.map((item) => (
              <option key={item.organization_id} value={item.organization_slug}>
                {item.organization_name}
              </option>
            ))}
          </select>
        </label>
        <div className="flex items-center gap-3">
          <Link
            href={`/${organizationSlug}/search`}
            aria-label="Global search"
            className="rounded-control p-2"
          >
            <Search size={18} />
          </Link>
          <button
            aria-label="Status center"
            title="Status center"
            className="rounded-control p-2"
            onClick={() => window.dispatchEvent(new CustomEvent("kos:status-center"))}
          >
            <Bell size={18} />
          </button>
          <button
            ref={railTrigger}
            aria-label="Open evidence"
            aria-expanded={evidence}
            className="rounded-control p-2"
            onClick={() => setEvidence(true)}
          >
            <PanelRight size={18} />
          </button>
          <details className="relative">
            <summary className="cursor-pointer text-sm">
              {me.user.display_name ?? me.user.email ?? "Account"}
            </summary>
            <div className="absolute right-0 z-40 mt-3 flex w-44 flex-col gap-2 rounded-panel border border-line bg-surface-0 p-3 shadow-popover">
              {(["light", "dark", "system"] as const).map((theme) => (
                <button
                  key={theme}
                  className="text-left capitalize"
                  onClick={() => setTheme(theme)}
                >
                  {theme} theme
                </button>
              ))}
              <Link href="/signout">Sign out</Link>
            </div>
          </details>
        </div>
      </header>
      <div className="flex min-h-0 flex-1">
        <nav
          aria-label="Main navigation"
          className={`shrink-0 overflow-y-auto border-r border-line bg-surface-0 p-2 ${collapsed ? "w-16" : "w-16 min-[1024px]:w-sidebar"}`}
        >
          <button
            aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
            aria-expanded={!collapsed}
            className="mb-3 rounded-control p-3"
            onClick={() => {
              const next = !collapsed;
              saveCollapsed(String(next));
            }}
          >
            <Menu size={18} />
          </button>
          {navigation
            .filter(
              (item) => !item.permission || hasPermission(membership.permissions, item.permission),
            )
            .map((item) => {
              const href = `/${organizationSlug}/${item.path}`;
              return (
                <Link
                  key={item.path}
                  href={href}
                  title={item.title}
                  aria-label={item.title}
                  aria-current={pathname === href ? "page" : undefined}
                  className="mb-1 flex items-center gap-3 rounded-control px-3 py-2 text-sm text-ink-secondary hover:bg-surface-2 aria-[current=page]:bg-accent-soft aria-[current=page]:text-accent"
                >
                  <span aria-hidden className="w-4 shrink-0 text-center font-mono">
                    {item.title.slice(0, 1)}
                  </span>
                  {!collapsed && <span className="hidden min-[1024px]:inline">{item.title}</span>}
                </Link>
              );
            })}
        </nav>
        <main id="main-content" className="min-w-0 flex-1 overflow-auto p-5 md:p-8">
          {children}
        </main>
        {evidence && (
          <EvidenceRail
            userId={me.user.id}
            onClose={() => {
              setEvidence(false);
              railTrigger.current?.focus();
            }}
          >
            <p className="text-sm text-ink-secondary">
              Select a citation or source to inspect its evidence here.
            </p>
          </EvidenceRail>
        )}
      </div>
    </div>
  );
}
