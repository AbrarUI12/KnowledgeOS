import { afterEach, describe, expect, it, vi } from "vitest";
import PrimitivesPage from "./page";

vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("not-found");
  },
}));
afterEach(() => vi.unstubAllEnvs());

describe("design-system preview visibility", () => {
  it("is available in the production static Pages showcase", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("ENABLE_DEV_ROUTES", "");
    vi.stubEnv("KOS_STATIC_EXPORT", "1");
    expect(() => PrimitivesPage()).not.toThrow();
  });
  it("remains opt-in for a production server deployment", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("ENABLE_DEV_ROUTES", "");
    vi.stubEnv("KOS_STATIC_EXPORT", "");
    expect(() => PrimitivesPage()).toThrow("not-found");
  });
});
