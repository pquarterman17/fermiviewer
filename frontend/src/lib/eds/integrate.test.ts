import { describe, expect, it } from "vitest";

import type { Spectrum } from "../api";
import { integrateWindow } from "./integrate";

// An 11-channel spectrum with a peak on channels 4–6 over a sloping
// background. The reference nets below were produced by running the backend
// this module ports — src/fermiviewer/calc/eds_maps.element_map — on this exact
// spectrum reshaped to a 1×1×11 cube. If the two ever diverge, the readout
// under the spectrum stops describing the map beside it.
const spec: Spectrum = {
  energy: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
  counts: [2, 3, 4, 10, 40, 12, 5, 4, 3, 2, 1],
  units: "keV",
};

describe("integrateWindow", () => {
  it("sums the raw window with bg='none'", () => {
    const r = integrateWindow(spec, 4, 6, "none")!;
    expect(r.channels).toBe(3);
    expect(r.gross).toBe(62);
    expect(r.background).toBe(0);
    expect(r.net).toBe(62); // element_map(..., bg="none") → 62.0
    expect(r.sigma).toBeCloseTo(Math.sqrt(62), 10);
  });

  it("matches the backend's two-sided linear background", () => {
    const r = integrateWindow(spec, 4, 6, "linear")!;
    // flanks are one peak-width wide: channels 2–3 (rate 3.5) and 7–8 (4.5),
    // so bg = 0.5·(3.5 + 4.5)·3 = 12
    expect(r.background).toBeCloseTo(12, 10);
    expect(r.net).toBeCloseTo(50, 10); // element_map(..., bg="linear") → 50.0
    // gross + 0.25·nPeak²·(L/nL² + H/nH²) = 62 + 2.25·(7/4 + 9/4)
    expect(r.sigma).toBeCloseTo(Math.sqrt(71), 10);
  });

  it("matches the backend's Kramers continuum", () => {
    const r = integrateWindow(spec, 4, 6, "bremsstrahlung", { e0Kev: 20 })!;
    expect(r.net).toBeCloseTo(56.8975527361736, 9);
    expect(r.note).toBeUndefined();
  });

  it("reports a negative net rather than clamping it away", () => {
    // A window on the flat tail sits below its own flanking background; the
    // map clamps such a pixel to zero, but a scalar readout must not pretend
    // there is signal where there is none.
    const flat: Spectrum = {
      energy: [1, 2, 3, 4, 5, 6],
      counts: [10, 10, 1, 1, 10, 10],
      units: "keV",
    };
    const r = integrateWindow(flat, 3, 4, "linear")!;
    expect(r.net).toBeLessThan(0);
  });

  it("skips the background when a flank falls off the spectrum", () => {
    const r = integrateWindow(spec, 1, 2, "linear")!;
    expect(r.note).toBeUndefined(); // the high flank alone still works
    const edge = integrateWindow(
      { energy: [1, 2], counts: [5, 6], units: "keV" },
      1,
      2,
      "linear",
    )!;
    expect(edge.background).toBe(0);
    expect(edge.note).toMatch(/no flanking channels/);
  });

  it("refuses a Kramers background below the window", () => {
    const r = integrateWindow(spec, 4, 6, "bremsstrahlung", { e0Kev: 3 })!;
    expect(r.background).toBe(0);
    expect(r.note).toMatch(/beam energy/);
  });

  it("normalises a reversed window and reports the spectrum fraction", () => {
    const r = integrateWindow(spec, 6, 4, "none")!;
    expect([r.eLo, r.eHi]).toEqual([4, 6]);
    expect(r.total).toBe(86);
    expect(r.fraction).toBeCloseTo(62 / 86, 10);
  });

  it("returns null when no channel falls inside the window", () => {
    expect(integrateWindow(spec, 20, 21, "linear")).toBeNull();
  });
});
