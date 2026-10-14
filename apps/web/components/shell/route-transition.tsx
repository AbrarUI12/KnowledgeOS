"use client";

import { motion, useReducedMotion } from "motion/react";
import type { ReactNode } from "react";

export function RouteTransition({ children }: { children: ReactNode }) {
  const reduced = useReducedMotion();
  return (
    <motion.div
      initial={{ opacity: reduced ? 1 : 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: reduced ? 0 : 0.18 }}
    >
      {children}
    </motion.div>
  );
}
