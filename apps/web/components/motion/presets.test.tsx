import { describe, expect, it } from "vitest";

import { ENTER_OFFSET_PX } from "@/lib/motion/tokens";

import { fadeSlideVariants } from "./presets";

describe("fadeSlideVariants", () => {
  it("enters with opacity plus a small translation", () => {
    const v = fadeSlideVariants("up", false);
    expect(v.hidden).toEqual({ opacity: 0, x: 0, y: ENTER_OFFSET_PX });
    expect(ENTER_OFFSET_PX).toBeLessThanOrEqual(10); // plan §27.20.4: ≤ 6–10px
  });

  it("replaces movement with a pure fade under reduced motion", () => {
    for (const direction of ["up", "down", "left", "right"] as const) {
      const v = fadeSlideVariants(direction, true);
      expect(v.hidden).toEqual({ opacity: 0, x: 0, y: 0 });
      expect(v.exit).toMatchObject({ opacity: 0, x: 0, y: 0 });
      // State change stays visible: opacity still animates.
      expect(v.visible.opacity).toBe(1);
    }
  });
});
