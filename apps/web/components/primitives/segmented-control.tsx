"use client";

import * as React from "react";
import { cn } from "cn";
import { LayoutGroup, motion } from "motion/react";
import { RadioGroup as RadioGroupPrimitive } from "radix-ui";

import { duration, ease } from "@/lib/motion/tokens";

/**
 * Compact single-choice control (theme, density, view mode). Semantically a radio group (not tabs:
 * it switches a value, it doesn't reveal panels). Arrow keys move the selection (Radix).
 */
const SegmentedValueContext = React.createContext<string | undefined>(undefined);

type SegmentedControlProps = Omit<
  React.ComponentProps<typeof RadioGroupPrimitive.Root>,
  "orientation"
> & {
  "aria-label": string;
};

function SegmentedControl({
  className,
  value,
  defaultValue,
  onValueChange,
  ...props
}: SegmentedControlProps) {
  const [uncontrolled, setUncontrolled] = React.useState(defaultValue);
  const current = value ?? uncontrolled;
  const groupId = React.useId();

  return (
    <SegmentedValueContext.Provider value={current}>
      <LayoutGroup id={groupId}>
        <RadioGroupPrimitive.Root
          data-slot="segmented-control"
          orientation="horizontal"
          value={current}
          onValueChange={(next) => {
            if (value === undefined) setUncontrolled(next);
            onValueChange?.(next);
          }}
          className={cn(
            "inline-flex h-control-md w-fit items-center gap-0.5 rounded-control bg-surface-2 p-[3px]",
            className,
          )}
          {...props}
        />
      </LayoutGroup>
    </SegmentedValueContext.Provider>
  );
}

function SegmentedControlItem({
  className,
  children,
  value,
  ...props
}: React.ComponentProps<typeof RadioGroupPrimitive.Item>) {
  const active = React.useContext(SegmentedValueContext) === value;
  return (
    <RadioGroupPrimitive.Item
      data-slot="segmented-control-item"
      value={value}
      className={cn(
        "relative inline-flex h-full items-center justify-center gap-1.5 rounded-[6px] px-2.5 text-sm font-medium whitespace-nowrap text-ink-secondary transition-colors duration-(--duration-fast) hover:text-ink disabled:pointer-events-none disabled:opacity-50 data-[state=checked]:text-ink [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        className,
      )}
      {...props}
    >
      {active && (
        <motion.span
          layoutId="segmented-active-indicator"
          aria-hidden="true"
          transition={{ duration: duration.base, ease: ease.standard }}
          className="absolute inset-0 rounded-[6px] border border-line bg-surface-1"
        />
      )}
      <span className="relative inline-flex items-center gap-1.5">{children}</span>
    </RadioGroupPrimitive.Item>
  );
}

export { SegmentedControl, SegmentedControlItem };
