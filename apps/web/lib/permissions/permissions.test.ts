import { describe, expect, it } from "vitest";
import { hasPermission } from "@/lib/permissions";
import { navigation } from "@/components/shell/navigation";

describe("permission visibility", () => {
  it("requires an explicit grant, including for custom roles", () => {
    expect(hasPermission([], "members.manage")).toBe(false);
    expect(hasPermission(["query.execute"], "members.manage")).toBe(false);
    expect(hasPermission(["members.manage"], "members.manage")).toBe(true);
  });
  it("keeps administrative links out of a query-only member's navigation", () => {
    const visible = navigation.filter(
      (item) => !item.permission || hasPermission(["query.execute"], item.permission),
    );
    expect(visible.map((item) => item.title)).toContain("Ask");
    expect(visible.map((item) => item.title)).not.toContain("Members");
    expect(visible.map((item) => item.title)).not.toContain("Observe");
  });
});
