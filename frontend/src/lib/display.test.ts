// display.ts — client mirror of calc/render.py window semantics.
// autoWindow is the percentile auto-contrast used by the A shortcut,
// the Adjust ◑ button, and (since #45) the prefs-driven percentiles.

import { describe, expect, it } from "vitest";

import type { Raster16 } from "./api";
import {
  autoWindow,
  colorbarTicks,
  niceStep,
  toNorm,
  toReal,
} from "./display";

function raster(values: number[], vmin = 0, vmax = 100): Raster16 {
  return {
    data: new Uint16Array(values),
    w: values.length,
    h: 1,
    vmin,
    vmax,
    nFrames: null,
  };
}

describe("autoWindow", () => {
  it("clips single-pixel outliers at the default 0.5/99.5 percentiles", () => {
    // 1000 px: one black, one white, the rest mid-gray
    const vals = new Array<number>(1000).fill(30000);
    vals[0] = 0;
    vals[999] = 65535;
    const { lo, hi } = autoWindow(raster(vals));
    // extremes are inside the clipped tails → window collapses to the body
    expect(lo).toBeCloseTo(30000 / 65535, 3);
    expect(hi).toBeCloseTo(30001 / 65535, 3); // hi<=lo guard bumps by 1
  });

  it("keeps extremes when percentiles are 0/100 (#45 prefs path)", () => {
    const vals = new Array<number>(1000).fill(30000);
    vals[0] = 0;
    vals[999] = 65535;
    const { lo, hi } = autoWindow(raster(vals), 0, 100);
    expect(lo).toBe(0);
    expect(hi).toBe(1);
  });

  it("uniform ramp: tighter percentiles narrow the window symmetrically", () => {
    const vals = Array.from({ length: 65536 }, (_, i) => i);
    const w = autoWindow(raster(vals), 10, 90);
    expect(w.lo).toBeCloseTo(0.1, 2);
    expect(w.hi).toBeCloseTo(0.9, 2);
  });

  it("constant raster never returns hi <= lo", () => {
    const { lo, hi } = autoWindow(raster(new Array<number>(64).fill(12345)));
    expect(hi).toBeGreaterThan(lo);
  });
});

describe("toReal / toNorm", () => {
  const r = raster([0], -50, 150); // span 200
  it("round-trips through real units", () => {
    expect(toReal(0.25, r)).toBe(0);
    expect(toNorm(0, r)).toBeCloseTo(0.25, 12);
    expect(toNorm(toReal(0.8, r), r)).toBeCloseTo(0.8, 12);
  });

  it("toNorm clamps outside the raster range", () => {
    expect(toNorm(-999, r)).toBe(0);
    expect(toNorm(9999, r)).toBe(1);
  });

  it("degenerate vmin==vmax does not divide by zero", () => {
    const flat = raster([5], 7, 7);
    expect(Number.isFinite(toNorm(7, flat))).toBe(true);
  });
});

describe("niceStep", () => {
  it("picks 1·2·5 × 10ⁿ steps for ~5 ticks", () => {
    expect(niceStep(20)).toBe(5); // 0,5,10,15,20
    expect(niceStep(100)).toBe(20);
    expect(niceStep(1)).toBeCloseTo(0.2, 10);
    expect(niceStep(8)).toBe(2);
  });
  it("is safe on degenerate ranges", () => {
    expect(niceStep(0)).toBe(1);
    expect(niceStep(-5)).toBe(1);
  });
});

describe("colorbarTicks", () => {
  it("returns multiples of step within [lo, hi]", () => {
    expect(colorbarTicks(132.13, 152.1, 5)).toEqual([135, 140, 145, 150]);
  });
  it("snaps a near-zero tick to exactly 0", () => {
    expect(colorbarTicks(-2, 12, 5)).toEqual([0, 5, 10]);
  });
  it("bails out (empty) when the step would overflow the bar", () => {
    expect(colorbarTicks(0, 100, 0.1)).toEqual([]);
  });
  it("handles an invalid step or inverted range", () => {
    expect(colorbarTicks(0, 10, 0)).toEqual([]);
    expect(colorbarTicks(10, 0, 5)).toEqual([]);
  });
});
