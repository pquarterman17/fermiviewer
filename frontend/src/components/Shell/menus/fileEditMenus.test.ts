import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { buildFileMenu, recentImagesEntry } from "./fileEditMenus";
import type { Entry, MenuCtx } from "./menuTypes";

function storeStub(extra: Record<string, unknown> = {}) {
  return {
    openPaths: vi.fn().mockResolvedValue(undefined),
    setStatus: vi.fn(),
    order: [],
    selected: [],
    unavailable: {},
    saveProject: vi.fn().mockResolvedValue(undefined),
    openProject: vi.fn().mockResolvedValue(undefined),
    locateData: vi.fn().mockResolvedValue(undefined),
    ...extra,
  } as unknown as MenuCtx["store"];
}

function entry(menu: Entry[], startsWith: string): Entry {
  const found = menu.find((e) => (e.label ?? "").startsWith(startsWith));
  if (!found) throw new Error(`no File-menu entry starting "${startsWith}"`);
  return found;
}

describe("recentImagesEntry", () => {
  beforeEach(() => localStorage.clear());

  it("is a disabled placeholder without a submenu when there are no recents", () => {
    const entry = recentImagesEntry(storeStub());
    expect(entry.label).toBe("Recent Images");
    expect(entry.disabled).toBe(true);
    expect(entry.submenu).toBeUndefined();
  });

  it("is disabled on corrupt localStorage instead of throwing", () => {
    localStorage.setItem("fv_recent", "{not json[");
    expect(recentImagesEntry(storeStub()).disabled).toBe(true);
  });

  it("lists filenames in a submenu and opens the full path on click", () => {
    localStorage.setItem(
      "fv_recent",
      JSON.stringify(["C:\\data\\scan1.dm4", "/mnt/em/cube.mib"]),
    );
    const store = storeStub();
    const entry = recentImagesEntry(store);
    expect(entry.disabled).toBeUndefined();
    expect(entry.submenu?.map((e) => e.label)).toEqual([
      "scan1.dm4",
      "cube.mib",
    ]);
    entry.submenu?.[1]?.action?.();
    expect(store.openPaths).toHaveBeenCalledWith(["/mnt/em/cube.mib"]);
  });

  it("shows all eight persisted recents (the flat menu used to cap at 5)", () => {
    localStorage.setItem(
      "fv_recent",
      JSON.stringify(
        Array.from({ length: 9 }, (_, i) => `C:\\data\\f${i}.tif`),
      ),
    );
    expect(recentImagesEntry(storeStub()).submenu).toHaveLength(8);
  });
});

// A capability nothing can reach is not a feature: these assert the project
// format (ADR 0002) is actually invocable, and that the two payload modes are
// two distinct commands rather than one hidden behind a default.
describe("project entries in the File menu", () => {
  const ctx = (store: MenuCtx["store"]): MenuCtx =>
    ({ store, openFiles: vi.fn() }) as unknown as MenuCtx;

  afterEach(() => vi.restoreAllMocks());

  it("offers Save Project, Export Project Bundle, Open Project and Locate", () => {
    const menu = buildFileMenu(ctx(storeStub()));
    const labels = menu.map((e) => e.label ?? "");
    expect(labels).toContain("Save Project…");
    expect(labels).toContain("Export Project Bundle…");
    expect(labels).toContain("Open Project…");
    expect(labels.some((l) => l.startsWith("Locate Data Folder"))).toBe(true);
    // the retired v1 wording must not linger anywhere
    expect(labels.some((l) => l.includes("Session"))).toBe(false);
  });

  it("saves light and bundles explicitly — the mode is never guessed", () => {
    const store = storeStub({ order: ["a"] });
    vi.spyOn(window, "prompt").mockReturnValue("/p/study.fvp");
    const menu = buildFileMenu(ctx(store));

    entry(menu, "Save Project").action?.();
    expect(store.saveProject).toHaveBeenLastCalledWith("/p/study.fvp", "light");
    entry(menu, "Export Project Bundle").action?.();
    expect(store.saveProject).toHaveBeenLastCalledWith("/p/study.fvp", "bundle");
    entry(menu, "Open Project").action?.();
    expect(store.openProject).toHaveBeenCalledWith("/p/study.fvp");
  });

  it("can save a project whose images are ALL unavailable", () => {
    // the no-data-loss guarantee is worthless if the command is greyed out
    // exactly when the placeholders that need preserving are all there is
    const store = storeStub({
      order: [],
      unavailable: { a: { id: "a", name: "a.tif", rel: "a.tif" } },
    });
    const menu = buildFileMenu(ctx(store));
    expect(entry(menu, "Save Project").disabled).toBe(false);
    expect(entry(menu, "Export Project Bundle").disabled).toBe(false);
  });

  it("disables Save with nothing open at all", () => {
    const menu = buildFileMenu(ctx(storeStub()));
    expect(entry(menu, "Save Project").disabled).toBe(true);
  });

  it("counts what is unavailable and only enables Locate when some is", () => {
    expect(entry(buildFileMenu(ctx(storeStub())), "Locate Data Folder")).toEqual(
      expect.objectContaining({ label: "Locate Data Folder…", disabled: true }),
    );
    const store = storeStub({
      unavailable: {
        a: { id: "a", name: "a.tif", rel: "a.tif" },
        b: { id: "b", name: "b.tif", rel: "b.tif" },
      },
    });
    vi.spyOn(window, "prompt").mockReturnValue("/moved");
    const locate = entry(buildFileMenu(ctx(store)), "Locate Data Folder");
    expect(locate.label).toBe("Locate Data Folder… (2 unavailable)");
    expect(locate.disabled).toBe(false);
    locate.action?.();
    expect(store.locateData).toHaveBeenCalledWith("/moved");
  });

  it("does nothing when a path prompt is dismissed", () => {
    const store = storeStub({ order: ["a"] });
    vi.spyOn(window, "prompt").mockReturnValue(null);
    const menu = buildFileMenu(ctx(store));
    entry(menu, "Save Project").action?.();
    entry(menu, "Open Project").action?.();
    expect(store.saveProject).not.toHaveBeenCalled();
    expect(store.openProject).not.toHaveBeenCalled();
  });
});
