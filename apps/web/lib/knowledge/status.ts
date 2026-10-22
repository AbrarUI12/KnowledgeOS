import type { IngestionState } from "@/lib/api/knowledge";
import type { Status } from "@/components/primitives/status-badge";

const ACTIVE_STATES = new Set<IngestionState>([
  "RECEIVED",
  "VALIDATING",
  "MALWARE_SCAN",
  "PARSING",
  "NORMALIZING",
  "SECURITY_SCAN",
  "CHUNKING",
  "EMBEDDING",
  "INDEXING",
  "VERIFYING",
]);

export function isActiveIngestionState(state: IngestionState | null | undefined): boolean {
  return state !== null && state !== undefined && ACTIVE_STATES.has(state);
}

export function ingestionStatus(state: IngestionState | null | undefined): Status {
  if (state === "READY") return "success";
  if (state === "PENDING_APPROVAL") return "warning";
  if (state === "FAILED_RETRYABLE" || state === "FAILED_PERMANENT" || state === "QUARANTINED")
    return "danger";
  if (isActiveIngestionState(state)) return "progress";
  return "neutral";
}

export function ingestionLabel(state: IngestionState | null | undefined): string {
  if (!state) return "Not started";
  return state
    .toLowerCase()
    .split("_")
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join(" ");
}
