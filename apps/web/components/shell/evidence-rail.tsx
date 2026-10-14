"use client";

import { useRef, type ReactNode } from "react";
import { Dialog } from "radix-ui";
import { usePreference } from "@/components/shell/use-preference";
import { useMediaQuery } from "@/components/shell/use-media-query";

const MIN_WIDTH = 360;
const MAX_WIDTH = 440;
export const clampRailWidth = (width: number) => Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, width));

export function EvidenceRail({
  userId,
  children,
  onClose,
}: {
  userId: string;
  children: ReactNode;
  onClose: () => void;
}) {
  const [savedWidth, saveWidth] = usePreference(`kos:${userId}:evidence-width`, "400");
  const width = Number.isFinite(Number(savedWidth)) ? clampRailWidth(Number(savedWidth)) : 400;
  const setWidth = (next: number | ((previous: number) => number)) =>
    saveWidth(String(typeof next === "function" ? next(width) : next));
  const start = useRef<{ x: number; width: number } | null>(null);
  const desktop = useMediaQuery("(min-width: 1440px)");
  const pane = (
    <aside
      aria-label="Evidence"
      className="fixed inset-y-14 right-0 z-30 flex w-full border-l border-line bg-surface-0 shadow-popover md:max-w-full min-[1024px]:w-(--rail-width) min-[1440px]:relative min-[1440px]:inset-auto min-[1440px]:shrink-0 min-[1440px]:shadow-none"
      style={{ "--rail-width": `${width}px` } as React.CSSProperties}
    >
      <div
        role="separator"
        aria-label="Resize evidence pane"
        aria-orientation="vertical"
        aria-valuemin={MIN_WIDTH}
        aria-valuemax={MAX_WIDTH}
        aria-valuenow={width}
        tabIndex={0}
        className="hidden w-2 cursor-col-resize touch-none hover:bg-accent-soft min-[1024px]:block"
        onKeyDown={(event) => {
          if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
            event.preventDefault();
            setWidth((value) => clampRailWidth(value + (event.key === "ArrowLeft" ? 10 : -10)));
          } else if (event.key === "Home" || event.key === "End") {
            event.preventDefault();
            setWidth(event.key === "Home" ? MIN_WIDTH : MAX_WIDTH);
          }
        }}
        onPointerDown={(event) => {
          start.current = { x: event.clientX, width };
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        onPointerMove={(event) => {
          if (start.current)
            setWidth(clampRailWidth(start.current.width + start.current.x - event.clientX));
        }}
        onPointerUp={() => {
          start.current = null;
        }}
        onPointerCancel={() => {
          start.current = null;
        }}
      />
      <div className="min-w-0 flex-1 overflow-auto p-5">
        <div className="mb-5 flex items-center justify-between">
          <h2 id="evidence-title" className="font-semibold">
            Evidence
          </h2>
          <button
            onClick={onClose}
            className="rounded-control border border-control-border px-3 py-1"
          >
            Close evidence
          </button>
        </div>
        {children}
      </div>
    </aside>
  );
  if (desktop) return pane;
  return (
    <Dialog.Root
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-20 bg-scrim" />
        <Dialog.Content asChild aria-labelledby="evidence-title" aria-describedby={undefined}>
          {pane}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
