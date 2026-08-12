// Pins the pdf-scaling contract PopulationHistogram.tsx relies on: the
// fitted-curve overlay must integrate to ≈ N * binWidth over a range that
// contains (nearly) all of the distribution's mass — the classic
// histogram-overlay bug is an unscaled or mis-scaled curve that visually
// disagrees with the bars it's meant to explain.

import { describe, expect, it } from "vitest";

import type { DistFit, DistributionHistogram } from "./api/distributions";
import {
  binCenters,
  formatPopulationSummary,
  meanBinWidth,
  pdf,
  pickSizeValues,
  scaledPdfCurve,
} from "./populationHistogram";

function trapezoidIntegral(x: number[], y: number[]): number {
  let total = 0;
  for (let i = 1; i < x.length; i++) {
    total += ((y[i] + y[i - 1]) / 2) * (x[i] - x[i - 1]);
  }
  return total;
}

describe("pdf", () => {
  it("normal pdf matches the closed-form value at the mean", () => {
    // pdf(loc) = 1 / (scale * sqrt(2*pi))
    const v = pdf("normal", { loc: 10, scale: 2 }, 10);
    expect(v).toBeCloseTo(1 / (2 * Math.sqrt(2 * Math.PI)), 10);
  });

  it("normal pdf integrates to ≈ 1 over a wide range", () => {
    const n = 4000;
    const lo = -10;
    const hi = 10;
    const x: number[] = [];
    const y: number[] = [];
    for (let i = 0; i < n; i++) {
      const xi = lo + ((hi - lo) * i) / (n - 1);
      x.push(xi);
      y.push(pdf("normal", { loc: 0, scale: 1 }, xi));
    }
    expect(trapezoidIntegral(x, y)).toBeCloseTo(1, 3);
  });

  it("lognormal pdf is zero at and below loc", () => {
    expect(pdf("lognormal", { s: 0.4, loc: 0, scale: 2 }, 0)).toBe(0);
    expect(pdf("lognormal", { s: 0.4, loc: 0, scale: 2 }, -1)).toBe(0);
  });

  it("weibull pdf is zero below loc", () => {
    expect(pdf("weibull", { c: 2, loc: 0, scale: 3 }, -1)).toBe(0);
  });

  it("unknown scale <= 0 is treated as degenerate (returns 0)", () => {
    expect(pdf("normal", { loc: 0, scale: 0 }, 0)).toBe(0);
    expect(pdf("normal", { loc: 0, scale: -1 }, 0)).toBe(0);
  });
});

describe("scaledPdfCurve — THE histogram-overlay scaling contract", () => {
  it("integrates to ≈ N * binWidth for a normal fit spanning its mass", () => {
    const fit: DistFit = {
      kind: "normal",
      params: { loc: 10, scale: 1.5 },
      log_likelihood: 0,
      aic: 0,
      ks_statistic: 0,
      ks_pvalue: 1,
    };
    const n = 300;
    const binWidth = 0.5;
    // +/- 6 sigma comfortably contains all of a normal distribution's mass
    const { x, y } = scaledPdfCurve(fit, 10 - 9, 10 + 9, n, binWidth, 2000);
    const integral = trapezoidIntegral(x, y);
    expect(integral).toBeCloseTo(n * binWidth, 0); // within ~0.5 absolute
    expect(Math.abs(integral - n * binWidth) / (n * binWidth)).toBeLessThan(0.01);
  });

  it("integrates to ≈ N * binWidth for a lognormal fit spanning its mass", () => {
    const fit: DistFit = {
      kind: "lognormal",
      params: { s: 0.4, loc: 0, scale: Math.exp(1) },
      log_likelihood: 0,
      aic: 0,
      ks_statistic: 0,
      ks_pvalue: 1,
    };
    const n = 500;
    const binWidth = 0.2;
    const { x, y } = scaledPdfCurve(fit, 1e-6, 30, n, binWidth, 4000);
    const integral = trapezoidIntegral(x, y);
    expect(Math.abs(integral - n * binWidth) / (n * binWidth)).toBeLessThan(0.02);
  });

  it("doubling N doubles the curve height at every point (linear scaling)", () => {
    const fit: DistFit = {
      kind: "normal",
      params: { loc: 0, scale: 1 },
      log_likelihood: 0,
      aic: 0,
      ks_statistic: 0,
      ks_pvalue: 1,
    };
    const a = scaledPdfCurve(fit, -3, 3, 100, 0.5, 50);
    const b = scaledPdfCurve(fit, -3, 3, 200, 0.5, 50);
    for (let i = 0; i < a.y.length; i++) {
      expect(b.y[i]).toBeCloseTo(2 * a.y[i], 10);
    }
  });

  it("a wrong scaling (peak pdf instead of count-scaled) is detectably different", () => {
    // Regression guard against the classic bug: plotting the raw pdf
    // (unscaled) instead of pdf*N*binWidth would understate the curve
    // by a huge factor for realistic N — assert the correct curve's
    // peak is NOT close to the raw pdf's peak.
    const fit: DistFit = {
      kind: "normal",
      params: { loc: 0, scale: 1 },
      log_likelihood: 0,
      aic: 0,
      ks_statistic: 0,
      ks_pvalue: 1,
    };
    const n = 300;
    const binWidth = 0.5;
    // 401 points over [-4, 4] lands exactly on x=0 (the true peak) at i=200
    const { y } = scaledPdfCurve(fit, -4, 4, n, binWidth, 401);
    const rawPeak = pdf("normal", { loc: 0, scale: 1 }, 0);
    const scaledPeak = Math.max(...y);
    expect(scaledPeak).toBeCloseTo(rawPeak * n * binWidth, 6);
    expect(scaledPeak / rawPeak).toBeCloseTo(n * binWidth, 6);
    expect(scaledPeak).toBeGreaterThan(rawPeak * 10); // sanity: nowhere near unscaled
  });
});

describe("binCenters / meanBinWidth", () => {
  const h: DistributionHistogram = {
    edges: [0, 2, 4, 6, 8],
    counts: [1, 2, 3, 4],
  };

  it("computes the midpoint of each bin", () => {
    expect(binCenters(h)).toEqual([1, 3, 5, 7]);
  });

  it("computes the mean bin width", () => {
    expect(meanBinWidth(h)).toBeCloseTo(2, 10);
  });

  it("returns 0 for an empty histogram", () => {
    expect(meanBinWidth({ edges: [5], counts: [] })).toBe(0);
  });
});

describe("pickSizeValues", () => {
  it("uses calibrated values + unit when every object has one", () => {
    const r = pickSizeValues([10, 20, 30], [5, 10, 15], "nm");
    expect(r).toEqual({ values: [5, 10, 15], unit: "nm" });
  });

  it("falls back to px + unit px when any calibrated value is null (uncalibrated image)", () => {
    const r = pickSizeValues([10, 20, 30], [null, null, null], "nm");
    expect(r).toEqual({ values: [10, 20, 30], unit: "px" });
  });

  it("falls back to px when the calibrated array is empty", () => {
    const r = pickSizeValues([10, 20], [], "nm");
    expect(r).toEqual({ values: [10, 20], unit: "px" });
  });

  it("never mixes calibrated and px within one population", () => {
    // one null among otherwise-calibrated values must not slip a px
    // value into a nm-labelled population
    const r = pickSizeValues([10, 20, 30], [5, null, 15], "nm");
    expect(r.unit).toBe("px");
    expect(r.values).toEqual([10, 20, 30]);
  });
});

describe("formatPopulationSummary", () => {
  it("formats N, mean ± std, median [q1, q3] with units", () => {
    const line = formatPopulationSummary(
      {
        n: 42,
        n_dropped: 0,
        mean: 18.4,
        std: 3.2,
        min: 5,
        max: 30,
        median: 17.9,
        q1: 15.1,
        q3: 21.0,
      },
      "nm",
    );
    expect(line).toContain("N=42");
    expect(line).not.toContain("dropped");
    expect(line).toContain("mean");
    expect(line).toContain("18.4");
    expect(line).toContain("median 17.90 [15.10, 21.00] nm");
  });

  it("mentions dropped count when non-zero", () => {
    const line = formatPopulationSummary(
      {
        n: 10,
        n_dropped: 3,
        mean: 1,
        std: 0.1,
        min: 0.5,
        max: 1.5,
        median: 1,
        q1: 0.9,
        q3: 1.1,
      },
      "px",
    );
    expect(line).toContain("3 dropped");
  });
});
