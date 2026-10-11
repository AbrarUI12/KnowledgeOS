# Frontend design system — "Knowledge Instrument"

Implementation notes for plan.md §27 (design thesis, visual system, motion). Live preview: `make web` → http://localhost:3000/dev/primitives (development only; 404 in production builds unless `ENABLE_DEV_ROUTES=true`).

## Layers

| Layer | Where | Rule |
|---|---|---|
| Tokens | `apps/web/styles/tokens.css` | The **only** place raw color values may appear (enforced by `scripts/check-raw-colors.mjs` in `pnpm lint`). Light/dark via `[data-theme]`, density via `[data-density]`. |
| Theme mapping | `apps/web/app/globals.css` | Maps tokens into Tailwind (`bg-canvas`, `text-ink-secondary`, `rounded-control`, `h-control-md`, `shadow-popover`…) and maps shadcn's names (`primary`, `muted`, `border`…) onto the same tokens. |
| Primitives | `apps/web/components/primitives/` | shadcn/Radix components **restyled** to the tokens. No `dark:` overrides (tokens are theme-aware). No `outline-none` (one global `:focus-visible` outline). |
| Motion | `apps/web/lib/motion/tokens.ts`, `components/motion/` | Durations/easings from plan §27.20.2. `<MotionConfig reducedMotion="user">` at the root. |

## Token naming

- Surfaces: `canvas` (warm paper) → `surface-0/1/2`.
- Text: `ink`, `ink-secondary`, `ink-tertiary` (metadata), `ink-inverse`.
- Lines: `line` (decorative separators), `line-strong`, `control-border` (input boundaries, ≥ 3:1).
- Accent (`accent`, `accent-hover`, `accent-soft`, `on-accent`, `focus`): focus, selection, links, the primary action and evidence linkage only. Never a page background.
- Status: `success`, `warning`, `danger` (+ `-soft` backgrounds). Semantic only.
- Shape: `rounded-control` (8px) for controls, `rounded-panel` (11px) for contained panels, `rounded-full` only for tags/status pills.
- Heights: `h-control-sm|md|lg` = 28/34/40px. Panes: `w-sidebar`, `w-evidence`, `max-w-reading`.

## Accessibility guarantees (tested)

- `tests/contrast.test.ts` parses `tokens.css` and asserts WCAG 2.2 AA for every text token on every surface, status text on its soft background, and ≥ 3:1 for control borders and the focus ring, in **both** themes.
- Contrast adjustments from the plan's reference palette (plan §27.3 asks to "validate contrast and adjust"):

  | Token | Plan | Now | Reason |
  |---|---|---|---|
  | light `ink-tertiary` | #7A7F78 (3.7:1 on canvas) | #676B65 (≥ 4.6:1) | AA text |
  | light `warning` | #A16318 (4.4:1) | #965C16 (≥ 4.7:1) | AA text |
  | dark `ink-tertiary` | #858B82 | #878D84 | AA on surface-2 |
  | `control-border` (new) | – | light #85897A, dark #667066 | WCAG 1.4.11 non-text contrast |

- axe-core runs over the whole primitives showcase in Vitest (`components/dev/primitives-showcase.test.tsx`).
- `IconButton` requires `aria-label` at the type level. `StatusBadge` always pairs color with an icon and a text label.
- Single-choice controls (theme, density, view mode) use `SegmentedControl` (radio-group semantics), not Tabs.
- Skip link is the first focusable element on every page.

## Iconography

`lucide-react`, line icons only. Icons never replace labels for ambiguous enterprise actions (icon-only buttons get an accessible name and a tooltip). **Never** use sparkles, magic wands, robot heads or glowing orbs as "AI" decoration (plan §27.1, §27.3).

## Motion rules (plan §27.20)

- Enter: opacity + ≤ 8px translation (`FadeIn`). Under reduced motion it becomes a pure fade.
- Shared layout (`layoutId`) only where spatial continuity explains something: tab/segment indicators now; citation → evidence rail, rank changes and similar later.
- Overlays use a plain `bg-scrim`, **no backdrop blur** (glassmorphism is an anti-pattern, and blur is expensive to animate).
- Never animate `box-shadow`, blur or large backdrop filters continuously. No looping decorative motion.

## Anti-patterns (from plan §27.1, do not introduce)

Purple/blue aurora gradients · glowing AI orbs · galaxy backgrounds · app-wide glassmorphism · 24–32px rounded cards everywhere · chat bubbles for long answers · sparkle/wand icons · typewriter animations · bouncing dots without status · decorative 3D · parallax in working surfaces · hidden citations · animations that delay already-available data.
