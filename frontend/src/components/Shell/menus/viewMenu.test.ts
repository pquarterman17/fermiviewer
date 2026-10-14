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

function item(menu: Entry[], startsWith: string): Entry {
  const found = menu.find((e) => (e.label ?? "").startsWith(startsWith));
  if (!found) throw new Error(`no entry starting "${startsWith}"`);
  return found;
}

describe("View → Groups", () => {
  it("disables every entry with no selection and no groups", () => {
    const menu = groupsMenu({});
    for (const label of [
      "Group Selected",
      "Add Selected to Group",
      "Remove Selected from Groups",
      "Compare Two Groups",
      "Delete Group",
      "Delete All Groups",
    ]) {
      expect(item(menu, label).disabled).toBe(true);
    }
  });

  it("enables each entry once its inputs exist", () => {
    const menu = groupsMenu({
      selected: ["a"],
      imageGroups: [
        { id: "g1", name: "A", ids: ["a"] },
        { id: "g2", name: "B", ids: ["b"] },
      ],
    });
    expect(item(menu, "Group Selected").label).toBe("Group Selected (1)…");
    for (const label of [
      "Group Selected",
      "Add Selected to Group",
      "Remove Selected from Groups",
      "Compare Two Groups",
      "Delete Group",
      "Delete All Groups",
    ]) {
      expect(item(menu, label).disabled).toBe(false);
    }
  });
});
