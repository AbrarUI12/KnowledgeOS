import { cn } from "cn";
import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  Info,
  LoaderCircle,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import type * as React from "react";

/**
 * Semantic status pill (plan §27.3: pills only for tags/status). Color is never the only signal:
 * every status also has an icon and a text label (plan §27.24).
 */
const statuses = {
  success: { icon: CheckCircle2, className: "bg-success-soft text-success" },
  warning: { icon: AlertTriangle, className: "bg-warning-soft text-warning" },
  danger: { icon: XCircle, className: "bg-danger-soft text-danger" },
  info: { icon: Info, className: "bg-accent-soft text-accent" },
  progress: { icon: LoaderCircle, className: "bg-accent-soft text-accent" },
  neutral: { icon: CircleDashed, className: "bg-surface-2 text-ink-secondary" },
} satisfies Record<string, { icon: LucideIcon; className: string }>;

export type Status = keyof typeof statuses;

type StatusBadgeProps = Omit<React.ComponentProps<"span">, "children"> & {
  status: Status;
  children: React.ReactNode;
};

export function StatusBadge({ status, className, children, ...props }: StatusBadgeProps) {
  const { icon: Icon, className: tone } = statuses[status];
  return (
    <span
      data-slot="status-badge"
      data-status={status}
      className={cn(
        "inline-flex h-5 items-center gap-1 rounded-full px-2 text-xs font-medium whitespace-nowrap",
        tone,
        className,
      )}
      {...props}
    >
      <Icon
        aria-hidden="true"
        className={cn("size-3 shrink-0", status === "progress" && "motion-safe:animate-spin")}
      />
      {children}
    </span>
  );
}
