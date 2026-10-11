// @vitest-environment node
/**
 * WCAG 2.2 AA contrast for every text/surface token pair, in both themes (session.md S05, plan §27.3).
 * Parses styles/tokens.css directly, so changing a token can't silently break accessibility.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const css = readFileSync(fileURLToPath(new URL("../styles/tokens.css", import.meta.url)), "utf8");

function themeBlock(selector: string): Record<string, string> {
  const start = css.indexOf(selector);
  const body = css.slice(css.indexOf("{", start) + 1, css.indexOf("}", start));
  const tokens: Record<string, string> = {};
  for (const [, name, value] of body.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)) {
    tokens[name!] = value!.toLowerCase();
  }
  return tokens;
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const lin = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * lin(r!) + 0.7152 * lin(g!) + 0.0722 * lin(b!);
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi! + 0.05) / (lo! + 0.05);
}

const SURFACES = ["canvas", "surface-0", "surface-1", "surface-2"];
const TEXT = ["ink", "ink-secondary", "ink-tertiary", "accent", "success", "warning", "danger"];

const themes = {
  light: themeBlock(':root,\n[data-theme="light"]'),
  dark: themeBlock('[data-theme="dark"]'),
};

describe.each(Object.entries(themes))("%s theme", (_name, t) => {
  it("parsed the token sheet", () => {
    expect(Object.keys(t).length).toBeGreaterThan(15);
  });

  it.each(TEXT.flatMap((fg) => SURFACES.map((bg) => [fg, bg] as const)))(
    "%s text on %s meets 4.5:1",
    (fg, bg) => {
      expect(contrast(t[fg]!, t[bg]!)).toBeGreaterThanOrEqual(4.5);
    },
  );

  it.each([
    ["success", "success-soft"],
    ["warning", "warning-soft"],
    ["danger", "danger-soft"],
    ["accent", "accent-soft"],
    ["on-accent", "accent"],
  ] as const)("status text %s on %s meets 4.5:1", (fg, bg) => {
    expect(contrast(t[fg]!, t[bg]!)).toBeGreaterThanOrEqual(4.5);
  });

  it.each(SURFACES)("control border and focus ring on %s meet 3:1 (WCAG 1.4.11)", (bg) => {
    expect(contrast(t["control-border"]!, t[bg]!)).toBeGreaterThanOrEqual(3);
    expect(contrast(t["focus"]!, t[bg]!)).toBeGreaterThanOrEqual(3);
  });
});
