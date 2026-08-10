// Tests for lib/projectCompare.ts — the W4 item 24 deliverable's pure
// arithmetic. The known-answer test (10/20/30 -> mean 20) pins the
// mean/std convention directly, rather than only checking self-consistency.

import { describe, expect, it } from "vitest";

import type { ImageGroup } from "./groups";
import {
  compareCsvColumns,
  compareCsvRows,
  compareSamplesByParam,
  paramColumn,
} from "./projectCompare";
import type { RegionCandidate, RegionTableImage } from "./regionTable";

// A square filling the whole image (normalized 0-1 corners) — its area in
// px^2 is exactly width*height, so a calibrated pixel_size gives a round
// physical area, letting the fixtures below target exact 10/20/30 values.
function squareMeasure(id: string): RegionCandidate {
  return {
    id,
    kind: "polygon",
    pts: [
      { x: 0, y: 0 },
      { x: 1, y: 0 },
      { x: 1, y: 1 },
      { x: 0, y: 1 },
    ],
  };
}

/** A 1x1 px image whose single square region has area exactly `area` in
 *  physical units, by setting pixel_size = sqrt(area). */
function imageWithArea(area: number, unit = "um"): RegionTableImage {
  return { shape: [1, 1], pixel_size: Math.sqrt(area), pixel_unit: unit };
}

const g = (
  id: string,
  ids: string[],
  params?: ImageGroup["params"],
): ImageGroup => ({ id, name: id, ids, params });

describe("compareSamplesByParam", () => {
  it("pins the known answer: areas 10/20/30 give mean 20 and the stated population sd", () => {
    const groups = [g("s1", ["a", "b", "c"], { temp: { value: 400, unit: "degC" } })];
    const images: Record<string, RegionTableImage> = {
      a: imageWithArea(10),
      b: imageWithArea(20),
      c: imageWithArea(30),
    };
    const measures: Record<string, RegionCandidate[]> = {
      a: [squareMeasure("m1")],
      b: [squareMeasure("m2")],
      c: [squareMeasure("m3")],
    };
    const result = compareSamplesByParam(groups, images, measures, "temp");
    expect(result.rows).toHaveLength(1);
    const row = result.rows[0];
    expect(row.n).toBe(3);
    expect(row.mean).toBeCloseTo(20, 9);
    // population std of [10,20,30]: sqrt(((10)^2+0+(10)^2)/3) = sqrt(200/3)
    expect(row.std).toBeCloseTo(Math.sqrt(200 / 3), 9);
    expect(row.resultUnit).toBe("um");
    expect(row.paramValue).toBe(400);
    expect(row.paramUnit).toBe("degC");
    expect(result.resultUnit).toBe("um");
    expect(result.excluded).toHaveLength(0);
  });

  it("orders rows ascending by parameter value, not group-creation order", () => {
    const groups = [
      g("hot", ["a"], { temp: { value: 500 } }),
      g("cold", ["b"], { temp: { value: 100 } }),
      g("mid", ["c"], { temp: { value: 300 } }),
    ];
    const images: Record<string, RegionTableImage> = {
      a: imageWithArea(1),
      b: imageWithArea(1),
      c: imageWithArea(1),
    };
    const measures: Record<string, RegionCandidate[]> = {
      a: [squareMeasure("m1")],
      b: [squareMeasure("m2")],
      c: [squareMeasure("m3")],
    };
    const result = compareSamplesByParam(groups, images, measures, "temp");
    expect(result.rows.map((r) => r.sampleName)).toEqual(["cold", "mid", "hot"]);
  });

  it("skips a purely organisational group with no member images", () => {
    const groups = [g("project", []), g("sample", ["a"], { temp: { value: 1 } })];
    const images: Record<string, RegionTableImage> = { a: imageWithArea(5) };
    const measures: Record<string, RegionCandidate[]> = { a: [squareMeasure("m1")] };
    const result = compareSamplesByParam(groups, images, measures, "temp");
    expect(result.rows.map((r) => r.sampleName)).toEqual(["sample"]);
    // the project group is not a sample, so it is not reported as excluded either
    expect(result.excluded).toHaveLength(0);
  });

  it("reports a sample missing the chosen parameter, rather than dropping it silently", () => {
    const groups = [g("s1", ["a"])];
    const images: Record<string, RegionTableImage> = { a: imageWithArea(5) };
    const measures: Record<string, RegionCandidate[]> = { a: [squareMeasure("m1")] };
    const result = compareSamplesByParam(groups, images, measures, "temp");
    expect(result.rows).toHaveLength(0);
    expect(result.excluded).toEqual([
      { groupId: "s1", sampleName: "s1", reason: 'no "temp" parameter set' },
    ]);
  });

  it("reports a categorical (non-numeric) parameter value as excluded, not coerced", () => {
    const groups = [g("s1", ["a"], { substrate: { value: "MgO" } })];
    const images: Record<string, RegionTableImage> = { a: imageWithArea(5) };
    const measures: Record<string, RegionCandidate[]> = { a: [squareMeasure("m1")] };
    const result = compareSamplesByParam(groups, images, measures, "substrate");
    expect(result.rows).toHaveLength(0);
    expect(result.excluded[0].reason).toContain("categorical");
    expect(result.excluded[0].reason).toContain("MgO");
  });

  it("reports a sample with no drawn regions", () => {
    const groups = [g("s1", ["a"], { temp: { value: 1 } })];
    const images: Record<string, RegionTableImage> = { a: imageWithArea(5) };
    const measures: Record<string, RegionCandidate[]> = { a: [] };
    const result = compareSamplesByParam(groups, images, measures, "temp");
    expect(result.excluded[0].reason).toBe("no regions drawn on any of its images");
  });

  it("distinguishes 'drawn but uncalibrated' from 'nothing drawn'", () => {
    const groups = [g("s1", ["a"], { temp: { value: 1 } })];
    const images: Record<string, RegionTableImage> = {
      a: { shape: [1, 1], pixel_size: null, pixel_unit: "px" },
    };
    const measures: Record<string, RegionCandidate[]> = { a: [squareMeasure("m1")] };
    const result = compareSamplesByParam(groups, images, measures, "temp");
    expect(result.excluded[0].reason).toBe(
      "regions drawn but none of its images are calibrated",
    );
  });

  it("excludes a sample whose own images mix physical units", () => {
    const groups = [g("s1", ["a", "b"], { temp: { value: 1 } })];
    const images: Record<string, RegionTableImage> = {
      a: imageWithArea(5, "um"),
      b: imageWithArea(5, "nm"),
    };
    const measures: Record<string, RegionCandidate[]> = {
      a: [squareMeasure("m1")],
      b: [squareMeasure("m2")],
    };
    const result = compareSamplesByParam(groups, images, measures, "temp");
    expect(result.rows).toHaveLength(0);
    expect(result.excluded[0].reason).toContain("mix physical units");
  });

  it("excludes a sample whose unit disagrees with the table's shared unit", () => {
    const groups = [
      g("s1", ["a"], { temp: { value: 1 } }),
      g("s2", ["b"], { temp: { value: 2 } }),
    ];
    const images: Record<string, RegionTableImage> = {
      a: imageWithArea(5, "um"),
      b: imageWithArea(5, "nm"),
    };
    const measures: Record<string, RegionCandidate[]> = {
      a: [squareMeasure("m1")],
      b: [squareMeasure("m2")],
    };
    const result = compareSamplesByParam(groups, images, measures, "temp");
    expect(result.rows.map((r) => r.sampleName)).toEqual(["s1"]);
    expect(result.excluded[0].sampleName).toBe("s2");
    expect(result.excluded[0].reason).toContain("cannot combine");
  });

  it("resultUnit is null when nothing produced a usable number", () => {
    const groups = [g("s1", ["a"], { temp: { value: 1 } })];
    const images: Record<string, RegionTableImage> = { a: imageWithArea(5) };
    const measures: Record<string, RegionCandidate[]> = { a: [] };
    const result = compareSamplesByParam(groups, images, measures, "temp");
    expect(result.rows).toHaveLength(0);
    expect(result.resultUnit).toBeNull();
  });
});

describe("paramColumn", () => {
  it("appends an ASCII-safe unit token when a unit is present", () => {
    expect(paramColumn("anneal_temp", "degC")).toBe("anneal_temp_degC");
  });
  it("falls back to the bare name when there is no unit", () => {
    expect(paramColumn("substrate", null)).toBe("substrate");
  });
});

describe("compareCsvColumns / compareCsvRows", () => {
  it("derives every unit from the data — n is always a visible column", () => {
    const groups = [g("s1", ["a"], { anneal_temp: { value: 400, unit: "degC" } })];
    const images: Record<string, RegionTableImage> = { a: imageWithArea(20) };
    const measures: Record<string, RegionCandidate[]> = { a: [squareMeasure("m1")] };
    const result = compareSamplesByParam(groups, images, measures, "anneal_temp");
    expect(compareCsvColumns(result)).toEqual([
      "sample",
      "anneal_temp_degC",
      "n",
      "area_um2_mean",
      "area_um2_sd",
    ]);
    const rows = compareCsvRows(result.rows);
    expect(rows).toHaveLength(1);
    const [sample, paramValue, n, mean, std] = rows[0];
    expect(sample).toBe("s1");
    expect(paramValue).toBe(400);
    expect(n).toBe(1);
    expect(mean as number).toBeCloseTo(20, 9);
    expect(std as number).toBeCloseTo(0, 9);
  });
});
