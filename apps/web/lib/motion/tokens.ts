/**
 * Motion tokens (plan §27.20.2). Mirrors the CSS duration/easing tokens in styles/tokens.css.
 * Seconds (Motion's unit). Tune on real hardware; keep the names stable.
 */
export const duration = {
  instant: 0.08,
  fast: 0.14,
  base: 0.2,
  deliberate: 0.28,
  panel: 0.34,
} as const;

export const ease = {
  standard: [0.22, 1, 0.36, 1],
  enter: [0.16, 1, 0.3, 1],
  exit: [0.4, 0, 1, 1],
} as const satisfies Record<string, readonly [number, number, number, number]>;

/** Default entrance travel: opacity + a small translation (≤ 6–10px, plan §27.20.4). */
export const ENTER_OFFSET_PX = 8;

/** Above this many items, list/rank layout animations are disabled (plan §27.20.5). */
export const LAYOUT_ANIMATION_MAX_ITEMS = 50;
