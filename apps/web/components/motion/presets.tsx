"use client";

import { AnimatePresence, motion, useReducedMotion, type HTMLMotionProps } from "motion/react";
import type { ReactNode } from "react";

import { duration, ease, ENTER_OFFSET_PX } from "@/lib/motion/tokens";

type Direction = "up" | "down" | "left" | "right" | "none";

const offsets: Record<Direction, { x: number; y: number }> = {
  up: { x: 0, y: ENTER_OFFSET_PX },
  down: { x: 0, y: -ENTER_OFFSET_PX },
  left: { x: ENTER_OFFSET_PX, y: 0 },
  right: { x: -ENTER_OFFSET_PX, y: 0 },
  none: { x: 0, y: 0 },
};

/**
 * Enter/exit transition variants. With reduced motion, movement is replaced by a fade so state
 * changes stay visible but nothing travels across the screen (plan §27.20.9).
 */
export function fadeSlideVariants(direction: Direction, reduced: boolean) {
  const offset = reduced ? offsets.none : offsets[direction];
  return {
    hidden: { opacity: 0, x: offset.x, y: offset.y },
    visible: {
      opacity: 1,
      x: 0,
      y: 0,
      transition: { duration: duration.base, ease: ease.enter },
    },
    exit: {
      opacity: 0,
      x: offset.x / 2,
      y: offset.y / 2,
      transition: { duration: duration.fast, ease: ease.exit },
    },
  };
}

type FadeInProps = Omit<HTMLMotionProps<"div">, "initial" | "animate" | "exit" | "variants"> & {
  direction?: Direction;
};

/** Opacity + small translation on mount/unmount. Use inside <Presence> for exit animations. */
export function FadeIn({ direction = "up", children, ...props }: FadeInProps) {
  const reduced = useReducedMotion() ?? false;
  return (
    <motion.div
      variants={fadeSlideVariants(direction, reduced)}
      initial="hidden"
      animate="visible"
      exit="exit"
      {...props}
    >
      {children}
    </motion.div>
  );
}

/** Thin wrapper over AnimatePresence with the project default (`popLayout` avoids reflow jumps). */
export function Presence({ children }: { children: ReactNode }) {
  return (
    <AnimatePresence mode="popLayout" initial={false}>
      {children}
    </AnimatePresence>
  );
}
