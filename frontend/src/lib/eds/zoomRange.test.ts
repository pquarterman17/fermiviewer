import { describe, expect, it } from "vitest";

import {
  clampRange,
  frameWindow,
  panBy,
  zoomAbout,
  zoomBy,
  type XRange,
} from "./zoomRange";

const BOUNDS: XRange = [0, 20];

describe("clampRange", () => {
  it("collapses a full-width view to null so the axis returns to auto", () => {
    expect(clampRange([0, 20], BOUNDS, 0.1)).toBeNull();
    expect(clampRange([-5, 40], BOUNDS, 0.1)).toBeNull();
  });

  it("slides an over-hanging view inside the data instead of shrinking it", () => {
    expect(clampRange([-4, 2], BOUNDS, 0.1)).toEqual([0, 6]);
    expect(clampRange([18, 26], BOUNDS, 0.1)).toEqual([12, 20]);
  });

  it("enforces the minimum span", () => {
    const out = clampRange([10, 10.0001], BOUNDS, 1)!;
    expect(out[1] - out[0]).toBeCloseTo(1, 10);
    expect((out[0] + out[1]) / 2).toBeCloseTo(10.00005, 10);
  });

  it("normalises a reversed range", () => {
    expect(clampRange([8, 4], BOUNDS, 0.1)).toEqual([4, 8]);
  });
});

describe("zoomAbout", () => {
  it("keeps the anchor energy fixed — the wheel-zoom contract", () => {
    const out = zoomAbout([4, 12], BOUNDS, 6, 0.5, 0.1)!;
    // half the span, and 6 stays a quarter of the way in from the left
    expect(out[1] - out[0]).toBeCloseTo(4, 10);
    expect((6 - out[0]) / (out[1] - out[0])).toBeCloseTo(0.25, 10);
  });

  it("zooms out from the full range without leaving the data", () => {
    expect(zoomAbout(null, BOUNDS, 10, 2, 0.1)).toBeNull();
  });
});

describe("zoomBy / panBy", () => {
  it("zooms about the view centre", () => {
    expect(zoomBy([4, 12], BOUNDS, 0.5, 0.1)).toEqual([6, 10]);
  });

  it("pans by a fraction of the view width", () => {
    expect(panBy([4, 8], BOUNDS, 0.5, 0.1)).toEqual([6, 10]);
    expect(panBy([4, 8], BOUNDS, -0.5, 0.1)).toEqual([2, 6]);
  });

  it("stops panning at the data edge rather than scrolling past it", () => {
    expect(panBy([17, 20], BOUNDS, 0.5, 0.1)).toEqual([17, 20]);
  });

  it("has nowhere to pan a full-range view", () => {
    expect(panBy(null, BOUNDS, 0.5, 0.1)).toBeNull();
  });
});

describe("frameWindow", () => {
  it("centres the energy window with context on both sides", () => {
    const out = frameWindow(9.9, 10.1, BOUNDS, 0.1, 2.5)!;
    expect((out[0] + out[1]) / 2).toBeCloseTo(10, 10);
    expect(out[1] - out[0]).toBeCloseTo(0.2 * 6, 10);
  });

  it("returns null when framing would show everything anyway", () => {
    expect(frameWindow(0, 20, BOUNDS, 0.1)).toBeNull();
  });
});
