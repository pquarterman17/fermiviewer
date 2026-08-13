import { describe, expect, it } from "vitest";

import { formatTickLabel, niceLogTicks, niceTicks } from "./ticks";

describe("niceTicks", () => {
  it("steps a 0-1234 range to a clean 1-2-5 ladder that covers it", () => {
    // rough step 1234/5 ≈ 246.8 → magnitude 100, residual 2.468 → snaps up
    // to the next 1/2/5 rung, 5×100 = 500
    expect(niceTicks(0, 1234)).toEqual([0, 500, 1000, 1500]);
  });

  it("handles a negative-to-positive range symmetrically", () => {
    expect(niceTicks(-50, 30)).toEqual([-60, -40, -20, 0, 20, 40]);
  });

  it("is order-independent (min > max is accepted the same as min < max)", () => {
    expect(niceTicks(30, -50)).toEqual(niceTicks(-50, 30));
  });

  it("produces a clean ladder for a tiny sub-unit range", () => {
    expect(niceTicks(0.0001, 0.0009)).toEqual([0, 0.0002, 0.0004, 0.0006, 0.0008, 0.001]);
  });

  it("pads a degenerate (min === max) range instead of returning nothing", () => {
    expect(niceTicks(5, 5).length).toBeGreaterThan(1);
    expect(niceTicks(0, 0).length).toBeGreaterThan(1);
  });

  it("returns an empty ladder for non-finite input rather than throwing", () => {
    expect(niceTicks(Number.NaN, 10)).toEqual([]);
    expect(niceTicks(0, Number.POSITIVE_INFINITY)).toEqual([]);
  });

  it("honours a custom targetCount", () => {
    const coarse = niceTicks(0, 100, { targetCount: 2 });
    const fine = niceTicks(0, 100, { targetCount: 20 });
    expect(coarse.length).toBeLessThan(fine.length);
  });
});

describe("niceLogTicks", () => {
  it("lays out 1/2/5×10^k rungs spanning a multi-decade range", () => {
    expect(niceLogTicks(1, 500)).toEqual([
      1, 2, 5, 10, 20, 50, 100, 200, 500,
    ]);
  });

  it("stays within a single decade when the range doesn't cross one", () => {
    const ticks = niceLogTicks(2, 6);
    expect(ticks).toEqual([2, 5]);
  });

  it("rejects non-positive bounds — a log axis cannot represent them", () => {
    expect(niceLogTicks(-1, 10)).toEqual([]);
    expect(niceLogTicks(0, 10)).toEqual([]);
    expect(niceLogTicks(1, 0)).toEqual([]);
  });

  it("is order-independent", () => {
    expect(niceLogTicks(500, 1)).toEqual(niceLogTicks(1, 500));
  });
});

describe("formatTickLabel", () => {
  it("is trailing-zero-free", () => {
    expect(formatTickLabel(1.5)).toBe("1.5");
    expect(formatTickLabel(2)).toBe("2");
    expect(formatTickLabel(0.1)).toBe("0.1");
  });

  it("kills float representation noise", () => {
    expect(formatTickLabel(0.1 + 0.2)).toBe("0.3");
  });

  it("renders zero and non-finite values", () => {
    expect(formatTickLabel(0)).toBe("0");
    expect(formatTickLabel(Number.NaN)).toBe("");
    expect(formatTickLabel(Number.POSITIVE_INFINITY)).toBe("");
  });

  it("preserves negative sign", () => {
    expect(formatTickLabel(-20)).toBe("-20");
  });
});
