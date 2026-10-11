"use client";

import { MotionConfig } from "motion/react";
import { ThemeProvider } from "next-themes";
import type { ReactNode } from "react";

import { Toaster } from "@/components/primitives/sonner";
import { TooltipProvider } from "@/components/primitives/tooltip";
import { duration, ease } from "@/lib/motion/tokens";

/**
 * App-wide client providers:
 * - theme: light/dark/system via the `data-theme` attribute (tokens.css), persisted by next-themes;
 * - motion: `reducedMotion="user"` honours the OS setting everywhere (plan §27.20.9);
 * - tooltips and toasts.
 */
export function Providers({ children }: { children: ReactNode }) {
  return (
    <ThemeProvider
      attribute="data-theme"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
    >
      <MotionConfig
        reducedMotion="user"
        transition={{ duration: duration.base, ease: ease.standard }}
      >
        <TooltipProvider delayDuration={400}>
          {children}
          <Toaster />
        </TooltipProvider>
      </MotionConfig>
    </ThemeProvider>
  );
}
