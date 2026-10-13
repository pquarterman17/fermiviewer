import { describe, expect, it, vi } from "vitest";

import type { Entry, MenuCtx } from "./menuTypes";
import { buildViewMenu } from "./viewWindowHelpMenus";

function groupsMenu(extra: Record<string, unknown>): Entry[] {
  const store = {
    activeId: null,
    order: ["a", "b"],
    selected: [],
    images: { a: {}, b: {} },
    imageGroups: [],
    startSideBySide: vi.fn(),
    ...extra,
  } as unknown as MenuCtx["store"];
  const menu = buildViewMenu({ store, onFit: vi.fn(), onActualSize: vi.fn() } as unknown as MenuCtx);
  const groups = menu.find((e) => e.label === "Groups");
  if (!groups?.submenu) throw new Error("no View → Groups submenu");
  return groups.submenu;
}

describe("View → Groups", () => {
  it("needs a selection to group and a group to add to", () => {
    const [group, add, compare] = groupsMenu({});
    expect(group.disabled).toBe(true);
    expect(add.disabled).toBe(true);
    expect(compare.disabled).toBe(true);
  });

  it("enables each entry once its inputs exist", () => {
    const [group, add, compare] = groupsMenu({
      selected: ["a"],
      imageGroups: [
        { id: "g1", name: "A", ids: ["a"] },
        { id: "g2", name: "B", ids: ["b"] },
      ],
    });
    expect(group.label).toBe("Group Selected (1)…");
    expect(group.disabled).toBe(false);
    expect(add.disabled).toBe(false);
    expect(compare.disabled).toBe(false);
  });
});
