import { describe, expect, it } from "vitest";

import type { Measure } from "../../store/viewer";
import {
  canonicalCalibrationUnit,
  calibrationEntryLabel,
  calibrationLineAxis,
  convertCalibrationValue,
  positiveNumber,
} from "./calibrationUi";

const line = (x: number, y: number): Measure => ({
  id: "line",
  kind: "distance",
  pts: [{ x: 0, y: 0 }, { x, y }],
});

describe("calibrationLineAxis", () => {
  it("classifies in pattern pixels, including non-square displays", () => {
    expect(calibrationLineAxis(line(0.5, 0.02), [100, 200])).toEqual({
      axis: "column",
      pixels: 100,
    });
    expect(calibrationLineAxis(line(0.02, 0.5), [100, 200])).toEqual({
      axis: "row",
      pixels: 50,
    });
  });

  it("refuses diagonal and zero-length lines", () => {
    expect(calibrationLineAxis(line(0.5, 0.5), [100, 200])).toBeNull();
    expect(calibrationLineAxis(line(0, 0), [100, 200])).toBeNull();
  });
});

it("accepts only finite positive extent fields", () => {
  expect(positiveNumber("0.5")).toBe(0.5);
  for (const bad of ["", "0", "-1", "NaN", "Infinity"]) {
    expect(positiveNumber(bad)).toBeNull();
  }
});

it("labels stored square and anisotropic calibrations honestly", () => {
  const base = { pixel_size: 2, unit: "nm", note: "", saved: "today" };
  expect(calibrationEntryLabel(base)).toBe("2 nm/px");
  expect(calibrationEntryLabel({ ...base, pixel_spacing: [0.5, 2] })).toBe(
    "rows 0.5 · columns 2 nm/px",
  );
});

it("normalizes parser spellings and converts without changing length", () => {
  expect(canonicalCalibrationUnit("um")).toBe("µm");
  expect(canonicalCalibrationUnit("μm")).toBe("µm");
  expect(canonicalCalibrationUnit("angstrom")).toBe("Å");
  expect(canonicalCalibrationUnit("1/nm")).toBeNull();
  expect(convertCalibrationValue(2, "nm", "µm")).toBe(0.002);
  expect(convertCalibrationValue(0.002, "µm", "nm")).toBe(2);
});
