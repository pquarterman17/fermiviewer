import { describe, expect, it } from "vitest";

import { residual, rSquared } from "./fitQuality";

describe("residual", () => {
  it("computes observed − model point-wise", () => {
    expect(residual([10, 20, 30], [9, 19, 31])).toEqual([1, 1, -1]);
  });

  it("throws on a length mismatch", () => {
    expect(() => residual([1, 2], [1])).toThrow(/same length/);
  });
});

describe("rSquared", () => {
  it("is 1 for a perfect fit", () => {
    const actual = [1, 2, 3, 4, 5];
    expect(rSquared(actual, actual)).toBeCloseTo(1, 10);
  });

  it("matches a hand-computed value", () => {
    // mean=3, ss_tot=4+1+0+1+4=10; ss_res=(5-6)^2=1; R²=1-1/10=0.9
    expect(rSquared([1, 2, 3, 4, 5], [1, 2, 3, 4, 6])).toBeCloseTo(0.9, 10);
  });

  it("goes negative when the model is worse than the mean", () => {
    const actual = [1, 2, 3, 4, 5];
    const wild = [10, -8, 20, -5, 15];
    expect(rSquared(actual, wild)).toBeLessThan(0);
  });

  it("returns 0 (not NaN) when actual has zero variance", () => {
    const flat = [7, 7, 7, 7, 7];
    const got = rSquared(flat, [1, 2, 3, 4, 5]);
    expect(got).toBe(0);
    expect(Number.isFinite(got)).toBe(true);
  });

  it("throws on a length mismatch", () => {
    expect(() => rSquared([1, 2], [1])).toThrow(/same length/);
  });
});
