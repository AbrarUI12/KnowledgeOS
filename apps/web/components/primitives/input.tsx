import * as React from "react";
import { cn } from "cn";

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "h-control-md w-full min-w-0 rounded-control border border-control-border bg-surface-1 px-2.5 text-base text-ink transition-colors duration-(--duration-fast) placeholder:text-ink-tertiary file:inline-flex file:h-6 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-ink hover:border-ink-tertiary disabled:pointer-events-none disabled:cursor-not-allowed disabled:bg-surface-2 disabled:opacity-60 aria-invalid:border-danger",
        className,
      )}
      {...props}
    />
  );
}

export { Input };
