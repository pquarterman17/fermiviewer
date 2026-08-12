// sigmaBand.ts — pure ±σ band math + uPlot series/band composition
// (ANALYSIS_PRESENTATION_PLAN item 3). No DOM/uPlot instance needed here:
// these tests check the arrays and config object sigmaBand() hands back,
// not what a real canvas renders.

import { describe, expect, it } from "vitest";

import {
  BAND_LEGEND_ROW_CLASS,
  hexToRgba,
  sigmaBand,
  sigmaBounds,
} from "./sigmaBand";

describe("sigmaBounds", () => {
  it("hi = y + sigma, lo = y - sigma pointwise", () => {
    const { hi, lo } = sigmaBounds([10, 20, 30], [1, 2, 3]);
    expect(hi).toEqual([11, 22, 33]);
    expect(lo).toEqual([9, 18, 27]);
  });

  it("NaN sigma -> null hi/lo at that point only (a gap, not a poisoned axis)", () => {
    const { hi, lo } = sigmaBounds([10, 20, 30], [1, NaN, 3]);
    expect(hi).toEqual([11, null, 33]);
    expect(lo).toEqual([9, null, 27]);
  });

  it("null/undefined sigma -> null hi/lo", () => {
    const { hi, lo } = sigmaBounds([10, 20], [null, undefined]);
    expect(hi).toEqual([null, null]);
    expect(lo).toEqual([null, null]);
  });

  it("negative sigma -> null hi/lo (never silently flip hi below lo)", () => {
    const { hi, lo } = sigmaBounds([10], [-1]);
    expect(hi).toEqual([null]);
    expect(lo).toEqual([null]);
  });

  it("sigma == 0 is valid -> hi == lo == y (a degenerate, zero-width band)", () => {
    const { hi, lo } = sigmaBounds([10], [0]);
    expect(hi).toEqual([10]);
    expect(lo).toEqual([10]);
  });

  it("NaN or missing y -> null hi/lo even with a finite sigma", () => {
    const { hi, lo } = sigmaBounds([NaN, undefined, null], [1, 1, 1]);
    expect(hi).toEqual([null, null, null]);
    expect(lo).toEqual([null, null, null]);
  });

  it("throws on mismatched lengths", () => {
    expect(() => sigmaBounds([1, 2], [1])).toThrow();
  });
});

describe("hexToRgba", () => {
  it("parses a 6-digit hex colour", () => {
    expect(hexToRgba("#f43f5e", 0.2)).toBe("rgba(244, 63, 94, 0.2)");
  });

  it("is case-insensitive", () => {
    expect(hexToRgba("#F43F5E", 0.2)).toBe("rgba(244, 63, 94, 0.2)");
  });

  it("falls back to grey on an unparseable colour rather than throwing", () => {
    expect(hexToRgba("not-a-color", 0.5)).toBe("rgba(136, 136, 136, 0.5)");
  });
});

describe("sigmaBand", () => {
  const y = [10, 20, 30];
  const sigma = [1, 2, 3];

  it("pairs the hi series first, lo series second, matching the band's [hi, lo] indices", () => {
    const cfg = sigmaBand(y, sigma, "#3b82f6", 5, 6);
    expect(cfg.band.series).toEqual([5, 6]);
    expect(cfg.data[0]).toEqual([11, 22, 33]); // hi, at series[0]/index 5
    expect(cfg.data[1]).toEqual([9, 18, 27]); // lo, at series[1]/index 6
  });

  it("records the caller-supplied indices exactly, whatever they are", () => {
    const cfg = sigmaBand(y, sigma, "#3b82f6", 41, 42);
    expect(cfg.band.series).toEqual([41, 42]);
  });

  it("both boundary series are shown (uPlot only fills a band when both edges are)", () => {
    const cfg = sigmaBand(y, sigma, "#3b82f6", 1, 2);
    expect(cfg.series[0].show).toBe(true);
    expect(cfg.series[1].show).toBe(true);
  });

  it("marks both boundary series with the legend-hiding class and draws no stroke", () => {
    const cfg = sigmaBand(y, sigma, "#3b82f6", 1, 2);
    for (const s of cfg.series) {
      expect(s.class).toBe(BAND_LEGEND_ROW_CLASS);
      expect(s.width).toBe(0);
      expect(s.points?.show).toBe(false);
    }
  });

  it("colours the band fill from the element colour at the requested alpha", () => {
    const cfg = sigmaBand(y, sigma, "#3b82f6", 1, 2, { fillAlpha: 0.25 });
    expect(cfg.band.fill).toBe(hexToRgba("#3b82f6", 0.25));
  });

  it("NaN sigma at one point leaves only that point out of the band", () => {
    const cfg = sigmaBand(y, [1, NaN, 3], "#3b82f6", 1, 2);
    expect(cfg.data[0]).toEqual([11, null, 33]);
    expect(cfg.data[1]).toEqual([9, null, 27]);
  });
});
