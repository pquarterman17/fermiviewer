// grainsCsv: header provenance, one row per grain, column order,
// blanks for non-finite values, optional astm line.

import { describe, expect, it } from "vitest";

import { grainsToCsv } from "./grainsCsv";
import type { GrainResult } from "./api";

function makeResult(overrides: Partial<GrainResult> = {}): GrainResult {
  return {
    n_grains: 3,
    method: "gradient",
    labels: { id: "lbl1", name: "grains", kind: "image", shape: [64, 64] } as GrainResult["labels"],
    mean_diameter_px: 12.5,
    boundary_length_px: 300,
    boundary_network_px: 285.4,
    boundary_length_calibrated: null,
    n_boundary_segments: 8,
    n_triple_junctions: 4,
    astm_grain_size: 7.5,
    areas_px: [100, 200, 150],
    perimeters_px: [40, 55, 48],
    eccentricity: [0.3, 0.7, 0.5],
    unit: "px",
    ...overrides,
  };
}

describe("grainsToCsv", () => {
  it("emits a provenance header with image name and method", () => {
    const csv = grainsToCsv(makeResult(), { imageName: "sample.dm4", method: "gradient" });
    expect(csv).toContain("# image: sample.dm4");
    expect(csv).toContain("# method: gradient");
    expect(csv).toContain("# n_grains: 3");
  });

  it("includes astm_grain_size line when present", () => {
    const csv = grainsToCsv(makeResult(), { imageName: "x", method: "gradient" });
    expect(csv).toContain("# astm_grain_size: 7.5");
  });

  it("omits astm_grain_size line when null", () => {
    const csv = grainsToCsv(
      makeResult({ astm_grain_size: null }),
      { imageName: "x", method: "kmeans" },
    );
    expect(csv).not.toContain("# astm_grain_size");
  });

  it("emits correct column header", () => {
    const csv = grainsToCsv(makeResult(), { imageName: "x", method: "gradient" });
    expect(csv).toContain("grain_id,area_px,perimeter_crofton_px,eccentricity");
  });

  it("emits one data row per grain with 1-based ids", () => {
    const csv = grainsToCsv(makeResult(), { imageName: "x", method: "gradient" });
    const lines = csv.split("\n").filter((l) => !l.startsWith("#") && l.trim() !== "");
    // first line is the column header
    expect(lines).toHaveLength(4); // header + 3 data rows
    expect(lines[1]).toMatch(/^1,/);
    expect(lines[2]).toMatch(/^2,/);
    expect(lines[3]).toMatch(/^3,/);
  });

  it("grain_id=1 has correct area, perimeter, eccentricity values", () => {
    const csv = grainsToCsv(makeResult(), { imageName: "x", method: "gradient" });
    const lines = csv.split("\n").filter((l) => !l.startsWith("#") && l.trim() !== "");
    // lines[0] = header, lines[1] = first data row (grain 1)
    const [gid, area, perim, ecc] = lines[1].split(",");
    expect(gid).toBe("1");
    expect(Number(area)).toBeCloseTo(100);
    expect(Number(perim)).toBeCloseTo(40);
    expect(Number(ecc)).toBeCloseTo(0.3);
  });

  it("handles non-finite perimeter gracefully (blanks)", () => {
    const r = makeResult({ perimeters_px: [40, NaN, 48] });
    const csv = grainsToCsv(r, { imageName: "x", method: "gradient" });
    const dataLines = csv
      .split("\n")
      .filter((l) => !l.startsWith("#") && l.trim() !== "")
      .slice(1); // skip header
    const [, , perim2] = dataLines[1].split(",");
    expect(perim2).toBe(""); // NaN → blank
  });

  it("ends with a trailing newline", () => {
    const csv = grainsToCsv(makeResult(), { imageName: "x", method: "gradient" });
    expect(csv.endsWith("\n")).toBe(true);
  });
});
