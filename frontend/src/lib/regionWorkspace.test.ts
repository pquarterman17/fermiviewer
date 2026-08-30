import { describe, expect, it } from "vitest";

import type { ProjectRegion, ProjectRegions } from "./api";
import {
  duplicateRegionSet,
  nextRegionId,
  measureToRegionShape,
  regionShapeToMeasure,
  regionShapeSummary,
  regionVisibilityKey,
  sanitizeRegionUi,
  regionSummary,
} from "./regionWorkspace";
import type { Measure } from "../store/viewerTypes";

const region: ProjectRegion = {
  id: "grain-1",
  name: "Grain 1",
  region_class: "grain",
  meta: {},
  parts: [
    {
      mode: "include",
      shape: {
        kind: "polygon",
        outline: [[1, 1], [1, 8], [8, 8]],
        holes: [[[2, 2], [2, 3], [3, 3]]],
      },
    },
    { mode: "exclude", shape: { kind: "rect", bounds: [5, 5, 6, 6] } },
  ],
};

it("mints readable collision-free ids", () => {
  expect(nextRegionId("Grain boundary", ["grain-boundary"])).toBe("grain-boundary-2");
});

it("duplicates a set with independent geometry and unique region ids", () => {
  const workspace: ProjectRegions = {
    schema: 1,
    classes: [],
    sets: [{ id: "grains", name: "Grains", image_id: "i1", meta: {}, regions: [region] }],
  };
  const copy = duplicateRegionSet(workspace.sets[0], workspace);
  expect(copy.id).toBe("grains-copy");
  expect(copy.regions[0].id).toBe("grain-1-copy");
  expect(copy.regions[0].parts).toEqual(region.parts);
  expect(copy.regions[0].parts).not.toBe(region.parts);
});

describe("regionSummary", () => {
  it("makes compound geometry legible at a glance", () => {
    expect(regionSummary(region)).toBe("1 part · 1 exclusion · 1 hole");
  });

  it("distinguishes a true circle by reporting its radius", () => {
    expect(regionShapeSummary({ kind: "circle", bounds: [4, 4, 8, 8] }))
      .toBe("circle · r 2 px");
  });
});

it("scopes visibility and selection to a set", () => {
  const workspace: ProjectRegions = {
    schema: 1,
    classes: [],
    sets: [
      { id: "a", name: null, image_id: "i1", meta: {}, regions: [region] },
      { id: "b", name: null, image_id: "i1", meta: {}, regions: [{ ...region }] },
    ],
  };
  const ui = sanitizeRegionUi({
    selectedSetId: "a",
    selectedRegionId: "grain-1",
    hiddenSetIds: ["a", "gone"],
    hiddenRegionKeys: [
      regionVisibilityKey("b", "grain-1"),
      regionVisibilityKey("gone", "grain-1"),
    ],
  }, workspace);
  expect(ui.hiddenRegionKeys).toEqual([regionVisibilityKey("b", "grain-1")]);
  expect(ui.hiddenSetIds).toEqual(["a"]);
});

describe("annotation ↔ canonical region conversion", () => {
  it("converts normalized x/y rings to exact 0-based row/col geometry", () => {
    const measure: Measure = {
      id: "m1",
      kind: "lasso",
      pts: [{ x: 0.1, y: 0.25 }, { x: 0.8, y: 0.25 }, { x: 0.8, y: 0.75 }],
      holes: [[{ x: 0.2, y: 0.4 }, { x: 0.3, y: 0.4 }, { x: 0.3, y: 0.5 }]],
    };
    expect(measureToRegionShape(measure, 100, 80)).toEqual({
      kind: "polygon",
      outline: [[20, 10], [20, 80], [60, 80]],
      holes: [[[32, 20], [32, 30], [40, 30]]],
    });
  });

  it("sorts drag bounds and preserves the ROI/ellipse distinction", () => {
    const ellipse: Measure = {
      id: "m2",
      kind: "ellipse",
      pts: [{ x: 0.8, y: 0.75 }, { x: 0.1, y: 0.25 }],
    };
    expect(measureToRegionShape(ellipse, 100, 80)).toEqual({
      kind: "ellipse",
      bounds: [20, 10, 60, 80],
    });
  });

  it("loads editable shapes back onto the same normalized annotation rails", () => {
    const shape = {
      kind: "polygon" as const,
      outline: [[20, 10], [20, 80], [60, 80]] as [number, number][],
      holes: [[[32, 20], [32, 30], [40, 30]]] as [number, number][][],
    };
    expect(regionShapeToMeasure(shape, 100, 80)).toEqual({
      kind: "polygon",
      pts: [{ x: 0.1, y: 0.25 }, { x: 0.8, y: 0.25 }, { x: 0.8, y: 0.75 }],
      holes: [[{ x: 0.2, y: 0.4 }, { x: 0.3, y: 0.4 }, { x: 0.3, y: 0.5 }]],
    });
  });

  it("refuses a lossy annotation representation", () => {
    expect(regionShapeToMeasure({ kind: "circle", bounds: [1, 1, 5, 5] }, 10, 10)).toBeNull();
    expect(regionShapeToMeasure({
      kind: "rect",
      bounds: [1, 1, 5, 5],
      holes: [[[2, 2], [2, 3], [3, 3]]],
    }, 10, 10)).toBeNull();
  });
});
