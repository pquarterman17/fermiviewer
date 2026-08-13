import { describe, expect, it } from "vitest";

import type { AxisCalOut } from "../../../lib/api";
import {
  calibratedToPx,
  detCalibration,
  formatCalibratedRadius,
  pxToCalibrated,
  roundForDisplay,
} from "./mradConversion";

function axis(scale: number, units: string): AxisCalOut {
  return { scale, origin: 0, units };
}

describe("detCalibration", () => {
  it("returns the scale/units when both detector axes agree and are calibrated", () => {
    expect(detCalibration([axis(0.123, "mrad"), axis(0.123, "mrad")])).toEqual({
      scale: 0.123,
      units: "mrad",
    });
  });

  it("returns null when det_axes is missing or too short", () => {
    expect(detCalibration(undefined)).toBeNull();
    expect(detCalibration(null)).toBeNull();
    expect(detCalibration([])).toBeNull();
    expect(detCalibration([axis(0.1, "mrad")])).toBeNull();
  });

  it("returns null when either axis is uncalibrated (bare .mib, no .hdr sidecar)", () => {
    expect(detCalibration([axis(1, ""), axis(1, "")])).toBeNull();
    expect(detCalibration([axis(0.1, "mrad"), axis(1, "")])).toBeNull();
  });

  it("returns null when the two axes disagree on units — never silently picks one", () => {
    expect(detCalibration([axis(0.1, "mrad"), axis(0.2, "1/nm")])).toBeNull();
  });

  it("returns null for a zero or non-finite scale even with a unit label", () => {
    expect(detCalibration([axis(0, "mrad"), axis(0, "mrad")])).toBeNull();
    expect(detCalibration([axis(NaN, "mrad"), axis(NaN, "mrad")])).toBeNull();
  });
});

describe("pxToCalibrated / calibratedToPx", () => {
  it("is a linear scale in each direction", () => {
    expect(pxToCalibrated(10, 0.5)).toBe(5);
    expect(calibratedToPx(5, 0.5)).toBe(10);
  });

  it("round-trips px -> calibrated -> px", () => {
    const scale = 0.0734;
    const px = 42.5;
    expect(calibratedToPx(pxToCalibrated(px, scale), scale)).toBeCloseTo(px, 9);
  });

  // Mutation guard: swapping `*` for `/` (or vice versa) in either function
  // must fail this — a fixed scale and a fixed px give an EXACT expected
  // calibrated value, not just "some finite number".
  it("mrad = px * scale, exactly — a broken conversion factor must fail here", () => {
    expect(pxToCalibrated(80, 0.1)).toBe(8);
    expect(pxToCalibrated(80, 0.1)).not.toBe(800); // catches * <-> / mixups
    expect(calibratedToPx(8, 0.1)).toBe(80);
  });
});

describe("roundForDisplay", () => {
  it("strips float noise so a value redisplays as what was typed", () => {
    const scale = 0.1;
    const typed = 12.5;
    const px = calibratedToPx(typed, scale);
    const back = pxToCalibrated(px, scale);
    expect(roundForDisplay(back)).toBe(12.5);
  });

  it("passes non-finite values through unchanged", () => {
    expect(roundForDisplay(NaN)).toBeNaN();
  });
});

describe("formatCalibratedRadius", () => {
  it("formats a calibrated radius with 3 significant figures", () => {
    expect(formatCalibratedRadius(80, { scale: 0.1, units: "mrad" })).toBe("≈ 8.00 mrad");
    expect(formatCalibratedRadius(123.456, { scale: 0.1, units: "mrad" })).toBe(
      "≈ 12.3 mrad",
    );
  });

  it("returns null when uncalibrated or the px value is non-finite", () => {
    expect(formatCalibratedRadius(80, null)).toBeNull();
    expect(formatCalibratedRadius(NaN, { scale: 0.1, units: "mrad" })).toBeNull();
  });
});
