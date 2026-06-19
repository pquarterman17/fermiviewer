// Tests for computeMeasureStats (lib/measureStats.ts).
// Mirrors fermi-viewer/+fermiViewer/+analysis/displayMeasurementStats.m:
// N / mean / std / min / max on distance-like measures; extended to
// angle and ROI groups.

import { describe, expect, it } from "vitest";

import type { Measure } from "../store/viewer";
import { computeMeasureStats, statsStatusLine } from "./measureStats";
import type { MeasureStatsInput } from "./measureStats";

// ---------------------------------------------------------------------------
// Helpers to build test fixtures
// ---------------------------------------------------------------------------

const IMG = { w: 100, h: 100 }; // 100×100 px image

/** Normalized distance measure: a horizontal line `len` px long. */
function distMeasure(id: string, lenPx: number): Measure {
  return {
    id,
    kind: "distance",
    pts: [
      { x: 0, y: 0.5 },
      { x: lenPx / IMG.w, y: 0.5 },
    ],
  };
}

/** Angle measure: 90° right-angle at origin. */
function angleMeasure(id: string): Measure {
  // vertex at (0.5, 0.5), ray A up, ray B right → 90°
  return {
    id,
    kind: "angle",
    pts: [
      { x: 0.5, y: 0.4 },  // a (up from vertex)
      { x: 0.5, y: 0.5 },  // vertex
      { x: 0.6, y: 0.5 },  // b (right of vertex)
    ],
  };
}

function base(overrides: Partial<MeasureStatsInput> = {}): MeasureStatsInput {
  return {
    measures: [],
    img: IMG,
    pixelSize: null,
    pixelUnit: "px",
    tilt: null,
    roiStats: {},
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Case 1: empty — no measures
// ---------------------------------------------------------------------------

describe("computeMeasureStats — empty", () => {
  it("returns total=0 and no groups", () => {
    const s = computeMeasureStats(base());
    expect(s.total).toBe(0);
    expect(s.groups).toHaveLength(0);
  });

  it("statsStatusLine handles no numeric measures", () => {
    const s = computeMeasureStats(base());
    expect(statsStatusLine(s)).toMatch(/N=0/);
  });
});

// ---------------------------------------------------------------------------
// Case 2: single distance measure
// ---------------------------------------------------------------------------

describe("computeMeasureStats — single distance", () => {
  const measures = [distMeasure("d1", 30)];
  const stats = computeMeasureStats(base({ measures }));

  it("total = 1, one group", () => {
    expect(stats.total).toBe(1);
    expect(stats.groups).toHaveLength(1);
  });

  it("group label and unit", () => {
    expect(stats.groups[0].label).toBe("Distance");
    expect(stats.groups[0].unit).toBe("px");
  });

  it("N / mean / std / min / max", () => {
    const g = stats.groups[0];
    expect(g.count).toBe(1);
    expect(g.mean).toBeCloseTo(30, 6);
    expect(g.std).toBeCloseTo(0, 6);  // single value → std = 0
    expect(g.min).toBeCloseTo(30, 6);
    expect(g.max).toBeCloseTo(30, 6);
  });

  it("statusLine matches MATLAB format: 'Stats: N=1, mean=30.00 ± 0.00 px'", () => {
    const line = statsStatusLine(stats);
    expect(line).toBe("Stats: N=1, mean=30.00 ± 0.00 px");
  });
});

// ---------------------------------------------------------------------------
// Case 3: mixed types — distance + angle + ROI
// ---------------------------------------------------------------------------

describe("computeMeasureStats — mixed types", () => {
  const roi1: Measure = {
    id: "roi1",
    kind: "roi",
    pts: [
      { x: 0.1, y: 0.1 },
      { x: 0.2, y: 0.2 },
    ],
  };
  const measures: Measure[] = [
    distMeasure("d1", 10),
    distMeasure("d2", 20),
    angleMeasure("a1"),
    roi1,
    // annotation — should be ignored
    { id: "t1", kind: "text", pts: [{ x: 0.5, y: 0.5 }], text: "label" },
  ];

  const roiStats = { roi1: { mean: 50, std: 5, min: 40, max: 60, area: 100, unit: "counts" } };
  const stats = computeMeasureStats(base({ measures, roiStats }));

  it("total counts ALL measures including annotations", () => {
    expect(stats.total).toBe(5);
  });

  it("produces 3 groups: Distance, Angle, ROI mean", () => {
    const labels = stats.groups.map((g) => g.label);
    expect(labels).toEqual(["Distance", "Angle", "ROI mean"]);
  });

  it("Distance group: N=2, mean=15, std=5", () => {
    const g = stats.groups.find((x) => x.label === "Distance")!;
    expect(g.count).toBe(2);
    expect(g.mean).toBeCloseTo(15, 5);
    // population std: sqrt(((10-15)^2 + (20-15)^2) / 2) = sqrt(25) = 5
    expect(g.std).toBeCloseTo(5, 5);
    expect(g.min).toBeCloseTo(10, 5);
    expect(g.max).toBeCloseTo(20, 5);
    expect(g.values).toEqual([10, 20]);  // sorted ascending
  });

  it("Angle group: 90°", () => {
    const g = stats.groups.find((x) => x.label === "Angle")!;
    expect(g.count).toBe(1);
    expect(g.mean).toBeCloseTo(90, 3);
    expect(g.unit).toBe("°");
  });

  it("ROI group: mean of roi means", () => {
    const g = stats.groups.find((x) => x.label === "ROI mean")!;
    expect(g.count).toBe(1);
    expect(g.mean).toBeCloseTo(50, 5);
  });

  it("statusLine uses Distance group (first group)", () => {
    const line = statsStatusLine(stats);
    expect(line).toMatch(/N=2/);
    expect(line).toMatch(/15\.00/);
  });
});

// ---------------------------------------------------------------------------
// Case 4: tilt-corrected distance (geometry=cross-section, angle=30°)
// ---------------------------------------------------------------------------

describe("computeMeasureStats — tilt-corrected distances", () => {
  // A vertical line 10 px long, tilt axis=Y, cross-section geometry, 30°
  // tiltDist: dy *= 1/sin(30°) = 2; corrected = 10*2 = 20
  const vert: Measure = {
    id: "v1",
    kind: "distance",
    pts: [
      { x: 0.5, y: 0.0 },
      { x: 0.5, y: 0.1 },   // 10 px
    ],
  };
  const tilt = { angle: 30, axis: "Y" as const, geometry: "cross-section" as const };
  const stats = computeMeasureStats(base({ measures: [vert], tilt }));

  it("applies tilt correction: 10 px × 1/sin(30°) = 20 px", () => {
    const g = stats.groups[0];
    expect(g.mean).toBeCloseTo(20, 4);
  });
});

// ---------------------------------------------------------------------------
// Case 5: calibrated pixel size
// ---------------------------------------------------------------------------

describe("computeMeasureStats — calibrated units", () => {
  const measures = [distMeasure("d1", 50)];  // 50 px
  const stats = computeMeasureStats(
    base({ measures, pixelSize: 0.2, pixelUnit: "nm" }),
  );

  it("converts to calibrated units (50 px × 0.2 nm/px = 10 nm)", () => {
    const g = stats.groups[0];
    expect(g.unit).toBe("nm");
    expect(g.mean).toBeCloseTo(10, 5);
  });
});

// ---------------------------------------------------------------------------
// Case 6: annotations only — no numeric groups
// ---------------------------------------------------------------------------

describe("computeMeasureStats — annotations only", () => {
  const measures: Measure[] = [
    { id: "t1", kind: "text", pts: [{ x: 0.1, y: 0.1 }], text: "hi" },
    { id: "ar1", kind: "arrow", pts: [{ x: 0, y: 0 }, { x: 1, y: 1 }] },
  ];
  const stats = computeMeasureStats(base({ measures }));

  it("total = 2, groups empty", () => {
    expect(stats.total).toBe(2);
    expect(stats.groups).toHaveLength(0);
  });
});
