import { beforeEach, describe, expect, it, vi } from "vitest";

import { recentImagesEntry } from "./fileEditMenus";
import type { MenuCtx } from "./menuTypes";

function storeStub() {
  return {
    openPaths: vi.fn().mockResolvedValue(undefined),
    setStatus: vi.fn(),
  } as unknown as MenuCtx["store"];
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
