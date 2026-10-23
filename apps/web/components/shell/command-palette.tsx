"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from "@/components/primitives/dialog";
import { Input } from "@/components/primitives/input";
import { navigation } from "./navigation";
import type { Permission } from "@/lib/api/client";

export function CommandPalette({
  organizationSlug,
  permissions,
}: {
  organizationSlug: string;
  permissions: Permission[];
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  useEffect(() => {
    function keydown(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((value) => !value);
        setQuery("");
      }
    }
    document.addEventListener("keydown", keydown);
    return () => document.removeEventListener("keydown", keydown);
  }, []);
  const items = navigation.filter(
    (item) =>
      (!item.permission || permissions.includes(item.permission)) &&
      item.title.toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent
        onKeyDown={(event) => {
          if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
          const links = Array.from(
            event.currentTarget.querySelectorAll<HTMLAnchorElement>("nav a"),
          );
          if (!links.length) return;
          event.preventDefault();
          const current = links.indexOf(document.activeElement as HTMLAnchorElement);
          links[
            (current + (event.key === "ArrowDown" ? 1 : -1) + links.length) % links.length
          ].focus();
        }}
      >
        <DialogTitle>Go to</DialogTitle>
        <DialogDescription>
          Find a workspace page. Use arrow keys or Tab to choose a result, then Enter to open it.
        </DialogDescription>
        <Input
          aria-label="Find a page"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          autoFocus
        />
        <nav aria-label="Page results">
          <ul className="space-y-1">
            {items.map((item) => (
              <li key={item.path}>
                <Link
                  className="block rounded-control p-2 hover:bg-surface-2"
                  href={`/${organizationSlug}/${item.path}`}
                  onClick={() => setOpen(false)}
                >
                  {item.title}
                </Link>
              </li>
            ))}
          </ul>
          {items.length === 0 && <p role="status">No matching pages.</p>}
        </nav>
      </DialogContent>
    </Dialog>
  );
}
