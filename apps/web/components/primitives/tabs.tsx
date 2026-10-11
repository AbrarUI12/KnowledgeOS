"use client";

import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "cn";
import { LayoutGroup, motion } from "motion/react";
import { Tabs as TabsPrimitive } from "radix-ui";

import { duration, ease } from "@/lib/motion/tokens";

/**
 * Tabs with a shared-layout active indicator (plan §27.20.3): the highlight slides between
 * triggers via Motion `layoutId`. Reduced motion is honoured globally by <MotionConfig>.
 * Keyboard behaviour (arrows, Home/End) comes from Radix.
 */
const TabsValueContext = React.createContext<string | undefined>(undefined);

function Tabs({
  className,
  orientation = "horizontal",
  value: valueProp,
  defaultValue,
  onValueChange,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Root>) {
  const [uncontrolled, setUncontrolled] = React.useState(defaultValue);
  const value = valueProp ?? uncontrolled;
  const groupId = React.useId();

  const handleChange = (next: string) => {
    if (valueProp === undefined) setUncontrolled(next);
    onValueChange?.(next);
  };

  return (
    <TabsValueContext.Provider value={value}>
      <LayoutGroup id={groupId}>
        <TabsPrimitive.Root
          data-slot="tabs"
          data-orientation={orientation}
          orientation={orientation}
          value={value}
          onValueChange={handleChange}
          className={cn("group/tabs flex gap-2 data-horizontal:flex-col", className)}
          {...props}
        />
      </LayoutGroup>
    </TabsValueContext.Provider>
  );
}

const tabsListVariants = cva(
  "group/tabs-list inline-flex w-fit items-center justify-center text-ink-secondary group-data-vertical/tabs:h-fit group-data-vertical/tabs:flex-col",
  {
    variants: {
      variant: {
        default: "h-control-md gap-0.5 rounded-control bg-surface-2 p-[3px]",
        line: "gap-3 border-b border-line bg-transparent",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

const TabsVariantContext = React.createContext<"default" | "line">("default");

function TabsList({
  className,
  variant = "default",
  ...props
}: React.ComponentProps<typeof TabsPrimitive.List> & VariantProps<typeof tabsListVariants>) {
  const resolved = variant ?? "default";
  return (
    <TabsVariantContext.Provider value={resolved}>
      <TabsPrimitive.List
        data-slot="tabs-list"
        data-variant={resolved}
        className={cn(tabsListVariants({ variant: resolved }), className)}
        {...props}
      />
    </TabsVariantContext.Provider>
  );
}

function TabsTrigger({
  className,
  children,
  value,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  const active = React.useContext(TabsValueContext) === value;
  const variant = React.useContext(TabsVariantContext);

  return (
    <TabsPrimitive.Trigger
      data-slot="tabs-trigger"
      value={value}
      className={cn(
        "relative inline-flex h-full flex-1 items-center justify-center gap-1.5 rounded-[6px] px-2.5 text-sm font-medium whitespace-nowrap text-ink-secondary transition-colors duration-(--duration-fast) group-data-vertical/tabs:w-full group-data-vertical/tabs:justify-start hover:text-ink disabled:pointer-events-none disabled:opacity-50 data-active:text-ink [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        variant === "line" && "rounded-none px-0.5 pb-2",
        className,
      )}
      {...props}
    >
      {active && (
        <motion.span
          layoutId="tabs-active-indicator"
          aria-hidden="true"
          transition={{ duration: duration.base, ease: ease.standard }}
          className={cn(
            "absolute",
            variant === "line"
              ? "inset-x-0 -bottom-px h-0.5 bg-accent"
              : "inset-0 rounded-[6px] border border-line bg-surface-1",
          )}
        />
      )}
      <span className="relative inline-flex items-center gap-1.5">{children}</span>
    </TabsPrimitive.Trigger>
  );
}

function TabsContent({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Content>) {
  return (
    <TabsPrimitive.Content
      data-slot="tabs-content"
      className={cn("flex-1 text-base", className)}
      {...props}
    />
  );
}

export { Tabs, TabsList, TabsTrigger, TabsContent, tabsListVariants };
