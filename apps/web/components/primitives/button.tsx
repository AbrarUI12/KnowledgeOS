import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "cn";
import { Slot } from "radix-ui";

/**
 * KnowledgeOS button. Control radius (not pill-shaped), token heights 28/34/40px, one accent
 * primary action per surface. Focus uses the global :focus-visible outline (globals.css).
 */
const buttonVariants = cva(
  "group/button inline-flex shrink-0 items-center justify-center gap-1.5 rounded-control border font-medium whitespace-nowrap select-none transition-[background-color,border-color,color] duration-(--duration-fast) ease-standard disabled:pointer-events-none disabled:opacity-50 aria-invalid:border-danger [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        primary: "border-transparent bg-accent text-on-accent hover:bg-accent-hover",
        secondary:
          "border-line-strong bg-surface-1 text-ink hover:border-control-border hover:bg-surface-0 aria-expanded:bg-surface-2",
        ghost:
          "border-transparent bg-transparent text-ink-secondary hover:bg-surface-2 hover:text-ink aria-expanded:bg-surface-2 aria-expanded:text-ink",
        danger:
          "border-transparent bg-danger-soft text-danger hover:bg-danger hover:text-ink-inverse",
        link: "h-auto border-transparent px-0 text-accent underline-offset-4 hover:underline",
      },
      size: {
        sm: "h-control-sm px-2.5 text-sm",
        md: "h-control-md px-3 text-base",
        lg: "h-control-lg px-4 text-base",
        "icon-sm": "size-(--control-sm)",
        "icon-md": "size-(--control-md)",
        "icon-lg": "size-(--control-lg)",
      },
    },
    defaultVariants: {
      variant: "secondary",
      size: "md",
    },
  },
);

type ButtonProps = React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
  };

function Button({ className, variant, size, asChild = false, ...props }: ButtonProps) {
  const Comp = asChild ? Slot.Root : "button";

  return (
    <Comp
      data-slot="button"
      data-variant={variant ?? "secondary"}
      data-size={size ?? "md"}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  );
}

type IconButtonProps = Omit<ButtonProps, "size" | "aria-label"> & {
  /** Required: icon-only controls must have an accessible name (plan §27.24). */
  "aria-label": string;
  size?: "sm" | "md" | "lg";
};

/** Icon-only button. The accessible label is enforced by the type and shown as a native tooltip. */
function IconButton({ size = "md", variant = "ghost", title, ...props }: IconButtonProps) {
  return (
    <Button
      size={`icon-${size}`}
      variant={variant}
      title={title ?? props["aria-label"]}
      {...props}
    />
  );
}

export { Button, IconButton, buttonVariants };
export type { ButtonProps, IconButtonProps };
