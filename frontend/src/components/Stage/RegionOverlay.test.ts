import { describe, expect, it } from "vitest";

import type { ProjectRegionSet } from "../../lib/api";
import { regionShapePath, visibleRegionPreviews } from "./RegionOverlay";

const view = { z: 1, px: 0.5, py: 0.5 };
const size = { w: 100, h: 100 };

describe("RegionOverlay geometry", () => {
  it("maps canonical row/col polygon vertices to screen x/y exactly", () => {
    const path = regionShapePath({
      kind: "polygon",
      outline: [[10, 20], [30, 40], [50, 20]],
      holes: [[[20, 24], [22, 28], [24, 24]]],
    }, view, size, size);
    expect(path).toBe("M20.00 10.00 L40.00 30.00 L20.00 50.00 Z M24.00 20.00 L28.00 22.00 L24.00 24.00 Z");
  });

  it("renders inclusive rectangle bounds as pixel footprints", () => {
    expect(regionShapePath({ kind: "rect", bounds: [10, 20, 12, 23] }, view, size, size))
      .toBe("M19.50 9.50 H23.50 V12.50 H19.50 Z");
  });

  it("uses a circle's true bounds without half-pixel expansion", () => {
    expect(regionShapePath({ kind: "circle", bounds: [4, 4, 8, 8] }, view, size, size))
      .toBe("M4.00 6.00 A2.00 2.00 0 1 0 8.00 6.00 A2.00 2.00 0 1 0 4.00 6.00 Z");
  });
});

describe("RegionOverlay visibility", () => {
  const sets: ProjectRegionSet[] = [{
    id: "s1",
    name: "Cells",
    image_id: "img1",
    meta: {},
    regions: [
      { id: "r1", name: "A", region_class: "cell", meta: {}, parts: [] },
      { id: "r2", name: "B", region_class: null, meta: {}, parts: [] },
    ],
  }];

  it("filters hidden sets and scoped region keys and resolves class colors", () => {
    const visible = visibleRegionPreviews(
      "img1",
      sets,
      [{ id: "cell", label: "Cell", color: "#00ff00", note: null }],
      [],
      ['["s1","r2"]'],
      "s1",
      "r1",
    );
    expect(visible).toHaveLength(1);
    expect(visible[0]).toMatchObject({ color: "#00ff00", selected: true });
    expect(visibleRegionPreviews("img1", sets, [], ["s1"], [], null, null)).toEqual([]);
  });
});
