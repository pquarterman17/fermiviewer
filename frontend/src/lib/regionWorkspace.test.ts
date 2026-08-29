import { describe, expect, it } from "vitest";

import type { ProjectRegion, ProjectRegions } from "./api";
import {
  duplicateRegionSet,
  nextRegionId,
  regionVisibilityKey,
  sanitizeRegionUi,
  regionSummary,
} from "./regionWorkspace";

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
