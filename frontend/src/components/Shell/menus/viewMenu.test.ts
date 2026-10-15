import { describe, expect, it, vi } from "vitest";

import type { Entry, MenuCtx } from "./menuTypes";
import { buildViewMenu, buildWindowMenu } from "./viewWindowHelpMenus";

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

describe("Window → Analysis Workspaces", () => {
  it("routes an AFM height map to the guided surface workspace", () => {
    const openTool = vi.fn();
    const store = {
      activeId: "height",
      images: {
        height: {
          id: "height", name: "Height", kind: "image", shape: [8, 8], dtype: "float64",
          pixel_size: 1, pixel_unit: "nm", value_unit: "nm", n_channels: null,
          energy_first: null, energy_last: null, energy_units: "", stage_tilt_deg: null,
          meta: { parser: "nanoscope", spm_channel_kind: "height" },
        },
      },
      openTool,
    } as unknown as MenuCtx["store"];
    const menu = buildWindowMenu({ store } as unknown as MenuCtx);
    const workspaces = menu.find((entry) => entry.label === "Analysis Workspaces")?.submenu;
    const surface = workspaces?.find((entry) => entry.label === "AFM Surface Analysis");
    expect(surface?.disabled).toBe(false);
    surface?.action?.();
    expect(openTool).toHaveBeenCalledWith("afmsurface");
  });
});
