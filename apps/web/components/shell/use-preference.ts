"use client";

import { useCallback, useSyncExternalStore } from "react";

const EVENT = "kos:preference";
export function usePreference(key: string, fallback: string) {
  const subscribe = useCallback((notify: () => void) => {
    window.addEventListener("storage", notify);
    window.addEventListener(EVENT, notify);
    return () => {
      window.removeEventListener("storage", notify);
      window.removeEventListener(EVENT, notify);
    };
  }, []);
  const snapshot = useCallback(() => {
    try {
      return localStorage.getItem(key) ?? fallback;
    } catch {
      return fallback;
    }
  }, [key, fallback]);
  const value = useSyncExternalStore(subscribe, snapshot, () => fallback);
  const save = useCallback(
    (next: string) => {
      try {
        localStorage.setItem(key, next);
      } catch {
        /* Preferences are optional. */
      }
      window.dispatchEvent(new Event(EVENT));
    },
    [key],
  );
  return [value, save] as const;
}
