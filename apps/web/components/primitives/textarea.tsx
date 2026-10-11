import * as React from "react";
import { cn } from "cn";

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "flex field-sizing-content min-h-16 w-full rounded-control border border-control-border bg-surface-1 px-2.5 py-2 text-base text-ink transition-colors duration-(--duration-fast) placeholder:text-ink-tertiary hover:border-ink-tertiary disabled:cursor-not-allowed disabled:bg-surface-2 disabled:opacity-60 aria-invalid:border-danger",
        className,
      )}
      {...props}
    />
  );
}

export { Textarea };
