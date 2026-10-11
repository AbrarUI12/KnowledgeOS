/** First focusable element on every page: jumps keyboard users past navigation (WCAG 2.4.1). */
export function SkipLink({ target = "main-content" }: { target?: string }) {
  return (
    <a
      href={`#${target}`}
      className="sr-only rounded-control bg-surface-1 px-3 py-2 font-medium text-ink shadow-popover focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-(--z-toast)"
    >
      Skip to main content
    </a>
  );
}
