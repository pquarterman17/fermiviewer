// geometry.ts — pure math shared by overlay labels, stats, and log.
// tiltDist MUST mirror calc/profiles.measure_distance (the backend
// test pins 16/sin30°=32; we pin the same cases client-side).

import { describe, expect, it } from "vitest";

import {
  areaPxToPhysical,
  boxProfileLine,
  fitView,
  niceScaleLength,
  physAngle,
  physDist,
  physicalScale,
  polygonStats,
  polygonStatsNormalized,
  polygonStatsNormalizedWithHoles,
  polygonStatsWithHoles,
  resolveScaleView,
  tiltDist,
  unitToNm,
  viewForPhysicalScale,
  type TiltSettings,
} from "./geometry";

const P = (x: number, y: number) => ({ x, y });

describe("physDist", () => {
  it("3-4-5 triangle, uncalibrated → px", () => {
    expect(physDist(P(0, 0), P(3, 4), null)).toEqual({ value: 5, unit: "px" });
  });

  it("calibrated multiplies by pixel size", () => {
    expect(physDist(P(0, 0), P(3, 4), 0.5)).toEqual({
      value: 2.5,
      unit: "cal",
    });
  });

  it("zero-length is 0", () => {
    expect(physDist(P(7, 7), P(7, 7), null).value).toBe(0);
  });
});

describe("physAngle", () => {
  it("right angle", () => {
    expect(physAngle(P(0, 0), P(1, 0), P(0, 1))).toBeCloseTo(90, 10);
  });

  it("collinear opposite rays → 180", () => {
    expect(physAngle(P(0, 0), P(-1, 0), P(1, 0))).toBeCloseTo(180, 10);
  });

  it("reflex angles wrap into [0, 180]", () => {
    // rays at +170° and −170° are 20° apart, not 340°
    const a = P(Math.cos((170 * Math.PI) / 180), Math.sin((170 * Math.PI) / 180));
    const b = P(Math.cos((-170 * Math.PI) / 180), Math.sin((-170 * Math.PI) / 180));
    expect(physAngle(P(0, 0), a, b)).toBeCloseTo(20, 10);
  });
});

describe("tiltDist (#34 — mirrors calc/profiles.measure_distance)", () => {
  const cs = (angle: number, axis: "X" | "Y" = "Y"): TiltSettings => ({
    angle,
    axis,
    geometry: "cross-section",
  });

  it("null tilt === physDist", () => {
    expect(tiltDist(P(0, 0), P(3, 4), null, null)).toEqual(
      physDist(P(0, 0), P(3, 4), null),
    );
  });

  it("angle 0 is off (no 1/sin(0) blow-up)", () => {
    expect(tiltDist(P(0, 0), P(0, 10), null, cs(0)).value).toBe(10);
  });

  it("cross-section Y at 30°: vertical 10 px → 20 (matches backend doctest)", () => {
    expect(tiltDist(P(0, 0), P(0, 10), null, cs(30)).value).toBeCloseTo(20, 9);
  });

  it("in-axis only: horizontal line unaffected by Y-axis tilt", () => {
    expect(tiltDist(P(0, 0), P(10, 0), null, cs(30)).value).toBeCloseTo(10, 9);
  });

  it("axis X scales the x component", () => {
    expect(tiltDist(P(0, 0), P(10, 0), null, cs(30, "X")).value).toBeCloseTo(
      20,
      9,
    );
  });

  it("surface geometry uses 1/cos θ", () => {
    const t: TiltSettings = { angle: 60, axis: "Y", geometry: "surface" };
    expect(tiltDist(P(0, 0), P(0, 10), null, t).value).toBeCloseTo(20, 9);
  });

  it("negative angle is equivalent (component is squared)", () => {
    expect(tiltDist(P(0, 0), P(0, 10), null, cs(-30)).value).toBeCloseTo(
      20,
      9,
    );
  });

  it("mixed components: only in-axis part scales", () => {
    // dx=3 untouched, dy=4 → 8 at 30° cross-section: √(9+64)
    expect(tiltDist(P(0, 0), P(3, 4), null, cs(30)).value).toBeCloseTo(
      Math.sqrt(73),
      9,
    );
  });

  it("calibration applies after correction", () => {
    const d = tiltDist(P(0, 0), P(0, 10), 0.5, cs(30));
    expect(d.unit).toBe("cal");
    expect(d.value).toBeCloseTo(10, 9); // 20 px × 0.5 nm/px
  });
});

describe("boxProfileLine (box-profile capture)", () => {
  it("wide box → horizontal centerline, width = short (vertical) side", () => {
    const r = boxProfileLine(P(10, 20), P(110, 60));
    expect(r).toEqual({
      p0: { x: 10, y: 40 },
      p1: { x: 110, y: 40 },
      width: 40,
    });
  });

  it("tall box → vertical centerline, width = horizontal side", () => {
    const r = boxProfileLine(P(10, 20), P(40, 220));
    expect(r).toEqual({
      p0: { x: 25, y: 20 },
      p1: { x: 25, y: 220 },
      width: 30,
    });
  });

  it("drag direction does not matter", () => {
    expect(boxProfileLine(P(110, 60), P(10, 20))).toEqual(
      boxProfileLine(P(10, 20), P(110, 60)),
    );
  });

  it("degenerate boxes return null", () => {
    expect(boxProfileLine(P(0, 0), P(100, 1))).toBeNull();
    expect(boxProfileLine(P(0, 0), P(1, 100))).toBeNull();
  });

  it("width is rounded and at least 1", () => {
    const r = boxProfileLine(P(0, 0), P(50, 2.4));
    expect(r!.width).toBe(2);
  });
});

describe("unitToNm (scale-bar unit dropdown)", () => {
  it("converts the three offered units", () => {
    expect(unitToNm("Å")).toBe(0.1);
    expect(unitToNm("nm")).toBe(1);
    expect(unitToNm("µm")).toBe(1000);
  });

  it("tolerates ASCII spellings and case", () => {
    expect(unitToNm("A")).toBe(0.1);
    expect(unitToNm("angstrom")).toBe(0.1);
    expect(unitToNm("um")).toBe(1000);
    expect(unitToNm(" NM ")).toBe(1);
  });

  it("returns null for non-length calibrations", () => {
    expect(unitToNm("1/nm")).toBeNull();
    expect(unitToNm("px")).toBeNull();
    expect(unitToNm("")).toBeNull();
  });
});

describe("niceScaleLength", () => {
  it("picks the largest 1/2/5×10ⁿ below max", () => {
    expect(niceScaleLength(7)).toBe(5);
    expect(niceScaleLength(43)).toBe(20);
    expect(niceScaleLength(100)).toBe(100);
    expect(niceScaleLength(0.3)).toBe(0.2);
  });
});

describe("physicalScale / viewForPhysicalScale / resolveScaleView (#6, constant-scale browsing)", () => {
  const img = { w: 512, h: 512 };
  const vp = { w: 800, h: 600 };
  const centre = { px: 0.5, py: 0.5 };

  it("a 100-unit feature is the same screen width for two differently-calibrated images", () => {
    const target = 1; // pixel_unit per screen px, shared across the series
    const pixelSizeA = 2; // pixel_unit per image px
    const pixelSizeB = 5;
    const viewA = viewForPhysicalScale(target, pixelSizeA, centre);
    const viewB = viewForPhysicalScale(target, pixelSizeB, centre);

    const featureUnits = 100;
    const screenWidthA = (featureUnits / pixelSizeA) * viewA.z;
    const screenWidthB = (featureUnits / pixelSizeB) * viewB.z;
    expect(screenWidthA).toBeCloseTo(screenWidthB, 10);
    expect(screenWidthA).toBeCloseTo(100, 10);
  });

  it("round-trips target scale through physicalScale", () => {
    for (const [pixelSize, target] of [
      [2, 0.5],
      [10, 20],
      [0.1, 0.2],
    ] as const) {
      const view = viewForPhysicalScale(target, pixelSize, centre);
      expect(physicalScale(view, pixelSize)).toBeCloseTo(target, 10);
    }
  });

  it("keeps the given centre fixed while changing scale", () => {
    const c = { px: 0.31, py: 0.72 };
    const view = viewForPhysicalScale(2, 3, c);
    expect(view.px).toBe(c.px);
    expect(view.py).toBe(c.py);
  });

  it("locked + calibrated uses the physical-scale view", () => {
    const got = resolveScaleView(1, 2, img, vp, centre);
    expect(got).toEqual(viewForPhysicalScale(1, 2, centre));
    expect(got).not.toEqual(fitView(img, vp));
  });

  it.each([
    ["not locked (targetScale null)", null, 2],
    ["uncalibrated (pixelSize null)", 1, null],
    ["uncalibrated (pixelSize 0)", 1, 0],
    ["uncalibrated (pixelSize NaN)", 1, NaN],
    ["uncalibrated (pixelSize Infinity)", 1, Infinity],
    ["uncalibrated (pixelSize negative)", 1, -2],
  ])("%s falls back to fitView exactly", (_label, targetScale, pixelSize) => {
    expect(resolveScaleView(targetScale, pixelSize, img, vp, centre)).toEqual(
      fitView(img, vp),
    );
  });
});

describe("polygonStats (#12, shoelace area/centroid/perimeter)", () => {
  it("unit square: known-answer area, centroid, perimeter", () => {
    const square = [P(0, 0), P(1, 0), P(1, 1), P(0, 1)];
    expect(polygonStats(square)).toEqual({
      areaPx2: 1,
      centroid: { x: 0.5, y: 0.5 },
      perimeterPx: 4,
    });
  });

  it("3-4-5 right triangle: known-answer area, centroid, perimeter", () => {
    const tri = [P(0, 0), P(4, 0), P(0, 3)];
    const { areaPx2, centroid, perimeterPx } = polygonStats(tri);
    expect(areaPx2).toBeCloseTo(6, 10);
    expect(centroid.x).toBeCloseTo(4 / 3, 10);
    expect(centroid.y).toBeCloseTo(1, 10);
    expect(perimeterPx).toBeCloseTo(12, 10);
  });

  it("non-convex (staircase L-shape) is exact, not a convex-hull approximation", () => {
    // 2x2 square with a 1x1 corner notched out — true area 3, not 4.
    const L = [P(0, 0), P(2, 0), P(2, 1), P(1, 1), P(1, 2), P(0, 2)];
    const { areaPx2, perimeterPx } = polygonStats(L);
    expect(areaPx2).toBeCloseTo(3, 10);
    expect(perimeterPx).toBeCloseTo(8, 10);
  });

  it("a duplicated closing point is not double-counted", () => {
    const square = [P(0, 0), P(1, 0), P(1, 1), P(0, 1)];
    const withDupeClose = [...square, P(0, 0)];
    expect(polygonStats(withDupeClose)).toEqual(polygonStats(square));
  });

  it("fewer than 3 points → area 0, not NaN", () => {
    expect(polygonStats([])).toEqual({
      areaPx2: 0,
      centroid: { x: 0, y: 0 },
      perimeterPx: 0,
    });
    expect(polygonStats([P(1, 1)]).areaPx2).toBe(0);
    expect(polygonStats([P(0, 0), P(1, 1)]).areaPx2).toBe(0);
  });

  it("self-intersecting input gets the signed shoelace result, uncorrected", () => {
    // Symmetric bowtie: two crossing triangular lobes of equal area
    // cancel exactly in the signed sum — this is what shoelace gives,
    // not a "fixed" true area, and that is intentional (see doc comment).
    const bowtie = [P(0, 0), P(1, 1), P(1, 0), P(0, 1)];
    expect(polygonStats(bowtie).areaPx2).toBeCloseTo(0, 10);
  });

  it("polygonStatsNormalized denormalizes by image dimensions", () => {
    const unitSquare = [P(0, 0), P(1, 0), P(1, 1), P(0, 1)];
    const got = polygonStatsNormalized(unitSquare, { w: 10, h: 20 });
    expect(got).toEqual({
      areaPx2: 200,
      centroid: { x: 5, y: 10 },
      perimeterPx: 60,
    });
  });
});

describe("areaPxToPhysical (#12, pixel_size² area conversion)", () => {
  it("multiplies by pixel_size squared (assumes square pixels)", () => {
    expect(areaPxToPhysical(100, 2)).toBe(400);
  });

  it("uncalibrated (null pixelSize) stays null", () => {
    expect(areaPxToPhysical(100, null)).toBeNull();
  });

  it("zero-area input converts to zero, not null", () => {
    expect(areaPxToPhysical(0, 2)).toBe(0);
  });
});

describe("polygonStatsWithHoles (#19, holes / multi-part regions)", () => {
  const outerSquare = (n: number) => [P(0, 0), P(n, 0), P(n, n), P(0, n)];
  const innerSquare = (x0: number, y0: number, n: number) => [
    P(x0, y0),
    P(x0 + n, y0),
    P(x0 + n, y0 + n),
    P(x0, y0 + n),
  ];

  it("known-answer: 100x100 outer minus a 20x20 hole = 9600 px^2", () => {
    const outer = outerSquare(100);
    const hole = innerSquare(40, 40, 20);
    const stats = polygonStatsWithHoles(outer, [hole]);
    expect(stats.areaPx2).toBeCloseTo(10000 - 400, 10);
  });

  it("no holes is IDENTICAL to plain polygonStats, not just equivalent", () => {
    const outer = outerSquare(100);
    expect(polygonStatsWithHoles(outer, [])).toEqual(polygonStats(outer));
  });

  it("reversing a hole's point order does not change the result", () => {
    const outer = outerSquare(100);
    const hole = innerSquare(40, 40, 20);
    const forward = polygonStatsWithHoles(outer, [hole]);
    const reversed = polygonStatsWithHoles(outer, [[...hole].reverse()]);
    expect(reversed).toEqual(forward);
  });

  it("perimeter is outer perimeter PLUS every hole's perimeter", () => {
    const outer = outerSquare(100);
    const hole = innerSquare(40, 40, 20);
    const stats = polygonStatsWithHoles(outer, [hole]);
    expect(stats.perimeterPx).toBeCloseTo(400 + 80, 10); // 4*100 + 4*20
  });

  it("multiple holes all subtract", () => {
    const outer = outerSquare(100);
    const holes = [innerSquare(5, 5, 10), innerSquare(60, 60, 10)];
    const stats = polygonStatsWithHoles(outer, holes);
    expect(stats.areaPx2).toBeCloseTo(10000 - 100 - 100, 10);
  });

  it("centroid shifts off-centre when the hole is off-centre", () => {
    // A hole in the right half pulls the net centroid left of centre.
    const outer = outerSquare(100);
    const hole = innerSquare(70, 40, 20);
    const stats = polygonStatsWithHoles(outer, [hole]);
    expect(stats.centroid.x).toBeLessThan(50);
  });

  it("a hole covering the whole outer ring clamps area to 0, not negative", () => {
    const outer = outerSquare(100);
    const hole = outerSquare(100); // same ring as a "hole"
    const stats = polygonStatsWithHoles(outer, [hole]);
    expect(stats.areaPx2).toBe(0);
    // degenerate net area falls back to the outer centroid
    expect(stats.centroid).toEqual(polygonStats(outer).centroid);
  });

  it("polygonStatsNormalizedWithHoles denormalizes outer + holes by image dimensions", () => {
    const outerNorm = [P(0, 0), P(1, 0), P(1, 1), P(0, 1)];
    const holeNorm = [P(0.4, 0.4), P(0.6, 0.4), P(0.6, 0.6), P(0.4, 0.6)];
    const img = { w: 100, h: 100 };
    const got = polygonStatsNormalizedWithHoles(outerNorm, [holeNorm], img);
    expect(got.areaPx2).toBeCloseTo(10000 - 400, 10);
  });
});
