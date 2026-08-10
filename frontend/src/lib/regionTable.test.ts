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

describe("regionPhysicalAreas", () => {
  it("returns physical areas for calibrated regions only", () => {
    const measures: RegionCandidate[] = [SQUARE, { ...SQUARE, id: "r2" }];
    expect(regionPhysicalAreas(measures, IMG_CALIBRATED)).toEqual([20000, 20000]);
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
