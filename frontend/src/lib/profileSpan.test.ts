import { describe, expect, it } from "vitest";

import { profileSpan, withSigma } from "./profileSpan";

const DIST = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9];
const INTENSITY = [0, 0, 0, 1, 4, 7, 9, 10, 10, 10];

describe("profileSpan", () => {
  it("measures the distance between the two points, whichever order", () => {
    const up = profileSpan(DIST, INTENSITY, 2, 7)!;
    const down = profileSpan(DIST, INTENSITY, 7, 2)!;
    expect(up.length).toBe(5);
    expect(down.length).toBe(5);
    expect(down.x0).toBe(2);
  });

  it("keeps only the samples inside the span, for the fit to use", () => {
    const span = profileSpan(DIST, INTENSITY, 2.5, 6.5)!;
    expect(span.x).toEqual([3, 4, 5, 6]);
    expect(span.y).toEqual([1, 4, 7, 9]);
  });

  it("reports the step across the span from its own end samples", () => {
    const span = profileSpan(DIST, INTENSITY, 2, 7)!;
    expect(span.y0).toBe(0);
    expect(span.y1).toBe(10);
    expect(span.step).toBe(10);
  });

  it("drops gaps rather than reading them as zero", () => {
    // a profile that ran off the raster has nulls, and a zero there would
    // drag a fitted edge toward a value that was never measured
    const gappy = [0, null, 0, 1, 4, 7, 9, 10, 10, 10];
    const span = profileSpan(DIST, gappy, 0, 9)!;
    expect(span.x).not.toContain(1);
    expect(span.y).not.toContain(null);
    expect(span.x).toHaveLength(9);
  });

  it("refuses a span too short to fit, instead of handing the fit a reject", () => {
    // fit_interface_width needs 4 points, so the boundary sits exactly
    // between a span holding 4 samples and one holding 3 — pinned here,
    // where the caller can explain the refusal, not inside the request
    expect(profileSpan(DIST, INTENSITY, 2, 5)?.x).toEqual([2, 3, 4, 5]);
    expect(profileSpan(DIST, INTENSITY, 2, 4)).toBeNull();
  });

  it("returns nothing for a span that misses the data entirely", () => {
    expect(profileSpan(DIST, INTENSITY, 40, 50)).toBeNull();
  });
});

describe("withSigma", () => {
  it("shows a value with its uncertainty", () => {
    expect(withSigma(12.3456, 0.0234, "nm")).toBe("12.3 ± 0.023 nm");
  });

  it("shows an absent uncertainty as absent, never as +/- 0", () => {
    expect(withSigma(12.3456, null, "nm")).toBe("12.3 nm");
    expect(withSigma(12.3456, NaN, "nm")).toBe("12.3 nm");
    expect(withSigma(12.3456, undefined, "nm")).toBe("12.3 nm");
  });
});
