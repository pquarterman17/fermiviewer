// eelsQuantCsv: header provenance, one row per element, column order,
// blanks for non-finite sigma.

import { describe, expect, it } from "vitest";

import { eelsQuantToCsv } from "./eelsQuantCsv";
import type { EelsQuantResult } from "./api";

function makeResult(overrides: Partial<EelsQuantResult> = {}): EelsQuantResult {
  return {
    elements: ["O", "Fe", "La"],
    atomic_percent: [60.0, 25.0, 15.0],
    atomic_percent_error: [0.8, 0.5, 0.4],
    intensity: [1.2e5, 4.8e4, 2.1e4],
    sigma: [3.5e-22, 1.1e-21, 8.7e-22],
    ...overrides,
  };
}

describe("eelsQuantToCsv", () => {
  it("emits a provenance header with image name and edge count", () => {
    const csv = eelsQuantToCsv(makeResult(), { imageName: "eels_spectrum.dm4" });
    expect(csv).toContain("# image: eels_spectrum.dm4");
    expect(csv).toContain("# n_edges: 3");
  });

  it("emits correct column header", () => {
    const csv = eelsQuantToCsv(makeResult(), { imageName: "x" });
    expect(csv).toContain("element,atomic_percent,atomic_percent_error,intensity,sigma");
  });

  it("emits one data row per element", () => {
    const csv = eelsQuantToCsv(makeResult(), { imageName: "x" });
    const lines = csv.split("\n").filter((l) => !l.startsWith("#") && l.trim() !== "");
    expect(lines).toHaveLength(4); // header + 3 data rows
  });

  it("first element row has correct values", () => {
    const csv = eelsQuantToCsv(makeResult(), { imageName: "x" });
    const lines = csv.split("\n").filter((l) => !l.startsWith("#") && l.trim() !== "");
    const [el, atPct, atErr, intensity, sigma] = lines[1].split(",");
    expect(el).toBe("O");
    expect(Number(atPct)).toBeCloseTo(60.0);
    expect(Number(atErr)).toBeCloseTo(0.8);
    expect(Number(intensity)).toBeCloseTo(1.2e5, -1);
    expect(Number(sigma)).toBeCloseTo(3.5e-22, -24);
  });

  it("second element row matches Fe values", () => {
    const csv = eelsQuantToCsv(makeResult(), { imageName: "x" });
    const lines = csv.split("\n").filter((l) => !l.startsWith("#") && l.trim() !== "");
    const [el] = lines[2].split(",");
    expect(el).toBe("Fe");
  });

  it("handles non-finite sigma gracefully (blanks)", () => {
    const r = makeResult({ sigma: [3.5e-22, NaN, 8.7e-22] });
    const csv = eelsQuantToCsv(r, { imageName: "x" });
    const lines = csv.split("\n").filter((l) => !l.startsWith("#") && l.trim() !== "");
    const [, , , , sigma2] = lines[2].split(",");
    expect(sigma2.trim()).toBe(""); // NaN → blank
  });

  it("handles an empty result (no edges)", () => {
    const r = makeResult({ elements: [], atomic_percent: [], intensity: [], sigma: [] });
    const csv = eelsQuantToCsv(r, { imageName: "x" });
    expect(csv).toContain("# n_edges: 0");
    const lines = csv.split("\n").filter((l) => !l.startsWith("#") && l.trim() !== "");
    expect(lines).toHaveLength(1); // header only
  });

  it("ends with a trailing newline", () => {
    const csv = eelsQuantToCsv(makeResult(), { imageName: "x" });
    expect(csv.endsWith("\n")).toBe(true);
  });
});
