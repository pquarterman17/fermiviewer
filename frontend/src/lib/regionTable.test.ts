import { describe, expect, it } from "vitest";

import type { Measure } from "../store/viewer";
import {
  areaPhysicalColumn,
  regionCsvColumns,
  regionCsvRows,
  regionPhysicalAreas,
  regionRows,
  unitToken,
  type RegionCandidate,
} from "./regionTable";

// A square filling the whole 100x50 image (normalized 0-1 corners).
const SQUARE: RegionCandidate = {
  id: "r1",
  kind: "polygon",
  pts: [
    { x: 0, y: 0 },
    { x: 1, y: 0 },
    { x: 1, y: 1 },
    { x: 0, y: 1 },
  ],
};

const IMG_CALIBRATED = { shape: [50, 100], pixel_size: 2, pixel_unit: "nm" };
const IMG_UNCALIBRATED = { shape: [50, 100], pixel_size: null, pixel_unit: "px" };

describe("regionRows", () => {
  it("selects only region-kind (polygon/lasso) measures, skipping others", () => {
    const measures: RegionCandidate[] = [
      { id: "d1", kind: "distance", pts: [{ x: 0, y: 0 }, { x: 1, y: 1 }] },
      SQUARE,
      { id: "roi1", kind: "roi", pts: [{ x: 0, y: 0 }, { x: 0.5, y: 0.5 }] },
      { id: "l1", kind: "lasso", pts: [{ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 0.5, y: 1 }] },
    ];
    const rows = regionRows(measures, IMG_CALIBRATED);
    expect(rows.map((r) => r.measureId)).toEqual(["r1", "l1"]);
    expect(rows.map((r) => r.kind)).toEqual(["polygon", "lasso"]);
  });

  it("a real store Measure[] (pre-item-14 kinds) is accepted with no cast", () => {
    // Demonstrates Measure is structurally assignable to RegionCandidate:
    // this compiles today even though MeasureKind doesn't have "polygon" yet.
    const real: Measure[] = [
      { id: "m1", kind: "roi", pts: [{ x: 0, y: 0 }, { x: 1, y: 1 }] },
      { id: "m2", kind: "distance", pts: [{ x: 0, y: 0 }, { x: 1, y: 0 }] },
    ];
    expect(regionRows(real, IMG_CALIBRATED)).toEqual([]);
  });

  it("labels from Measure.text, falling back to a stable generated name", () => {
    const measures: RegionCandidate[] = [
      { id: "a", kind: "polygon", pts: SQUARE.pts, text: "  Grain A  " },
      { id: "b", kind: "polygon", pts: SQUARE.pts },
      { id: "c", kind: "lasso", pts: SQUARE.pts, text: "" },
    ];
    const rows = regionRows(measures, IMG_CALIBRATED);
    expect(rows.map((r) => r.label)).toEqual(["Grain A", "Region 2", "Region 3"]);
  });

  it("computes areaPx2 from normalized pts × image shape", () => {
    const rows = regionRows([SQUARE], IMG_CALIBRATED);
    // full 100x50 image → area = 100*50 = 5000 px^2
    expect(rows[0].areaPx2).toBeCloseTo(5000, 6);
    expect(rows[0].perimeterPx).toBeCloseTo(300, 6); // 2*(100+50)
  });

  it("converts area to physical units via pixel_size^2 when calibrated", () => {
    const rows = regionRows([SQUARE], IMG_CALIBRATED);
    // pixel_size = 2 nm/px → area = 5000 px^2 * 2^2 = 20000 nm^2
    expect(rows[0].areaPhysical).toBeCloseTo(20000, 6);
  });

  it("uncalibrated images: physical area is null, never 0 or NaN; px^2 still populated", () => {
    const rows = regionRows([SQUARE], IMG_UNCALIBRATED);
    expect(rows[0].areaPhysical).toBeNull();
    expect(rows[0].areaPx2).toBeCloseTo(5000, 6);
  });

  it("areas are derived, not cached: changing pixel_size changes the reported area", () => {
    const a = regionRows([SQUARE], { ...IMG_CALIBRATED, pixel_size: 2 })[0].areaPhysical;
    const b = regionRows([SQUARE], { ...IMG_CALIBRATED, pixel_size: 3 })[0].areaPhysical;
    expect(a).toBeCloseTo(20000, 6);
    expect(b).toBeCloseTo(45000, 6); // 5000 * 3^2
    expect(a).not.toEqual(b);
  });
});

describe("regions with holes (plan item 19)", () => {
  // A 100x100 image with a 20x20 hole punched square in its centre —
  // matches the module's known-answer test: 10000 - 400 = 9600 px^2.
  const HOLED_IMG = { shape: [100, 100], pixel_size: 2, pixel_unit: "nm" };
  const HOLE_PTS = [
    { x: 0.4, y: 0.4 },
    { x: 0.6, y: 0.4 },
    { x: 0.6, y: 0.6 },
    { x: 0.4, y: 0.6 },
  ];
  const HOLED_SQUARE: RegionCandidate = {
    id: "h1",
    kind: "polygon",
    pts: SQUARE.pts,
    holes: [HOLE_PTS],
  };

  it("known-answer: net px^2 area subtracts the hole", () => {
    const rows = regionRows([HOLED_SQUARE], HOLED_IMG);
    expect(rows[0].areaPx2).toBeCloseTo(10000 - 400, 6);
  });

  it("known-answer: physical area is net area times pixel_size^2", () => {
    const rows = regionRows([HOLED_SQUARE], HOLED_IMG);
    // pixel_size = 2 nm/px -> (10000-400) * 2^2 = 38400
    expect(rows[0].areaPhysical).toBeCloseTo(9600 * 4, 6);
  });

  it("reversing the hole's point order does not change the area", () => {
    const reversedHole: RegionCandidate = {
      ...HOLED_SQUARE,
      id: "h2",
      holes: [[...HOLE_PTS].reverse()],
    };
    const forward = regionRows([HOLED_SQUARE], HOLED_IMG)[0];
    const reversed = regionRows([reversedHole], HOLED_IMG)[0];
    expect(reversed.areaPx2).toBeCloseTo(forward.areaPx2, 10);
    expect(reversed.areaPhysical).toBeCloseTo(forward.areaPhysical!, 10);
  });

  it("reports holeCount, 0 for pre-#19 regions", () => {
    const rows = regionRows([SQUARE, HOLED_SQUARE], IMG_CALIBRATED);
    expect(rows[0].holeCount).toBe(0);
  });

  it("reports holeCount for a holed region", () => {
    const rows = regionRows([HOLED_SQUARE], HOLED_IMG);
    expect(rows[0].holeCount).toBe(1);
  });

  it("an empty holes array behaves exactly like no holes field at all", () => {
    const withEmptyHoles: RegionCandidate = { ...SQUARE, holes: [] };
    const withoutHoles = regionRows([SQUARE], IMG_CALIBRATED)[0];
    const withHolesField = regionRows([withEmptyHoles], IMG_CALIBRATED)[0];
    expect(withHolesField.areaPx2).toBe(withoutHoles.areaPx2);
    expect(withHolesField.areaPhysical).toBe(withoutHoles.areaPhysical);
    expect(withHolesField.perimeterPx).toBe(withoutHoles.perimeterPx);
    expect(withHolesField.centroid).toEqual(withoutHoles.centroid);
  });
});

describe("regionPhysicalAreas", () => {
  it("returns physical areas for calibrated regions only", () => {
    const measures: RegionCandidate[] = [SQUARE, { ...SQUARE, id: "r2" }];
    expect(regionPhysicalAreas(measures, IMG_CALIBRATED)).toEqual([20000, 20000]);
  });

  it("single-ring (no-holes) output is UNCHANGED by the item-19 addition", () => {
    // Pinned expected value from before #19 existed: a full 100x50 image
    // (IMG_CALIBRATED) at pixel_size 2 -> 100*50*2^2 = 20000, exactly as
    // the pre-existing "returns physical areas for calibrated regions
    // only" case above already asserts. This test exists specifically to
    // name the regression it guards: adding `holes` support must not
    // perturb the holes-free code path's numbers by even a rounding ULP.
    const measures: RegionCandidate[] = [SQUARE];
    expect(regionPhysicalAreas(measures, IMG_CALIBRATED)).toEqual([20000]);
  });

  it("returns an empty array when the image is uncalibrated (no fabricated numbers)", () => {
    expect(regionPhysicalAreas([SQUARE], IMG_UNCALIBRATED)).toEqual([]);
  });

  it("returns an empty array when there are no region measures", () => {
    const measures: RegionCandidate[] = [
      { id: "d1", kind: "distance", pts: [{ x: 0, y: 0 }, { x: 1, y: 1 }] },
    ];
    expect(regionPhysicalAreas(measures, IMG_CALIBRATED)).toEqual([]);
  });
});

describe("unitToken", () => {
  it("translates µ/Å to ASCII and strips other punctuation", () => {
    expect(unitToken("µm")).toBe("um");
    expect(unitToken("μm")).toBe("um"); // Greek mu spelling
    expect(unitToken("Å")).toBe("A");
    expect(unitToken("nm")).toBe("nm");
    expect(unitToken("1/nm")).toBe("1nm");
  });

  it("never returns an empty string", () => {
    expect(unitToken("")).toBe("unit");
    expect(unitToken("²")).toBe("unit");
  });
});

describe("areaPhysicalColumn / regionCsvColumns", () => {
  it("states the real calibrated unit, not a hardcoded µm²", () => {
    expect(areaPhysicalColumn(IMG_CALIBRATED)).toBe("area_nm2");
    expect(areaPhysicalColumn({ ...IMG_CALIBRATED, pixel_unit: "µm" })).toBe("area_um2");
  });

  it("uses area_physical (no unit) when uncalibrated", () => {
    expect(areaPhysicalColumn(IMG_UNCALIBRATED)).toBe("area_physical");
  });

  it("regionCsvColumns embeds the same unit-derived header", () => {
    expect(regionCsvColumns(IMG_CALIBRATED)).toEqual([
      "label",
      "kind",
      "area_px2",
      "area_nm2",
      "perimeter_px",
      "centroid_x_px",
      "centroid_y_px",
    ]);
  });
});

describe("regionCsvRows", () => {
  it("carries null (not 0) for the physical column on uncalibrated regions", () => {
    const rows = regionRows([SQUARE], IMG_UNCALIBRATED);
    const csvRows = regionCsvRows(rows);
    expect(csvRows).toHaveLength(1);
    const [label, kind, areaPx2, areaPhysical] = csvRows[0];
    expect(label).toBe("Region 1");
    expect(kind).toBe("polygon");
    expect(areaPx2).toBeCloseTo(5000, 6);
    expect(areaPhysical).toBeNull();
  });

  it("carries the calibrated physical area when present", () => {
    const rows = regionRows([SQUARE], IMG_CALIBRATED);
    const [, , , areaPhysical] = regionCsvRows(rows)[0];
    expect(areaPhysical).toBeCloseTo(20000, 6);
  });
});
