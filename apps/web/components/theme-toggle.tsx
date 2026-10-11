"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";

import { SegmentedControl, SegmentedControlItem } from "@/components/primitives/segmented-control";

const options = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
] as const;

const subscribe = () => () => {};

/** Light / dark / system switch. The choice is persisted by next-themes (localStorage). */
export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  // The stored theme is only known on the client; render a stable value during SSR.
  const mounted = useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );

  return (
    <SegmentedControl
      aria-label="Color theme"
      value={mounted ? (theme ?? "system") : "system"}
      onValueChange={setTheme}
    >
      {options.map(({ value, label, icon: Icon }) => (
        <SegmentedControlItem key={value} value={value}>
          <Icon aria-hidden="true" />
          {label}
        </SegmentedControlItem>
      ))}
    </SegmentedControl>
  );
}
