import { describe, expect, it } from "vitest";

import type { Spectrum } from "../api";
import { integrateEdge } from "./integrate";

/** energy axis 100..1000 eV in 2 eV steps. */
function axis(): number[] {
  const e: number[] = [];
  for (let v = 100; v <= 1000; v += 2) e.push(v);
  return e;
}

/** Exact power law A·E^−r — linear in log-log, so the fit must be exact. */
function powerlawSpec(a: number, r: number): Spectrum {
  const energy = axis();
  return {
    energy,
    counts: energy.map((e) => a * e ** -r),
    units: "eV",
  };
}

function withBox(spec: Spectrum, lo: number, hi: number, add: number): Spectrum {
  return {
    ...spec,
    counts: spec.counts.map((c, i) =>
      spec.energy[i] >= lo && spec.energy[i] <= hi ? c + add : c,
    ),
  };
}

const SIGNAL = { lo: 532, hi: 580 }; // 25 channels on the 2 eV axis
const BG = { lo: 400, hi: 500 };

describe("integrateEdge", () => {
  it("recovers ~zero net on a pure power-law continuum", () => {
    const r = integrateEdge(powerlawSpec(1e10, 2.5), SIGNAL, BG)!;
    expect(Math.abs(r.net)).toBeLessThan(1e-6 * r.gross);
    expect(r.channels).toBe(25);
    expect(r.note).toBeUndefined();
  });

  it("recovers a planted edge on top of the continuum, and the fit params", () => {
    const spec = withBox(powerlawSpec(1e10, 2.5), SIGNAL.lo, SIGNAL.hi, 500);
    const r = integrateEdge(spec, SIGNAL, BG)!;
    expect(r.net).toBeCloseTo(500 * 25, 3);
    expect(r.params!.A).toBeCloseTo(1e10, -4); // relative ~1e-6 of 1e10
    expect(r.params!.r).toBeCloseTo(2.5, 6);
  });

  it("supports the exponential model exactly", () => {
    const energy = axis();
    const base: Spectrum = {
      energy,
      counts: energy.map((e) => 1000 * Math.exp(-0.005 * e)),
      units: "eV",
    };
    const spec = withBox(base, SIGNAL.lo, SIGNAL.hi, 200);
    const r = integrateEdge(spec, SIGNAL, BG, "exponential")!;
    expect(r.net).toBeCloseTo(200 * 25, 3);
    expect(r.params!.b).toBeCloseTo(-0.005, 9);
  });

  it("sums directly, with a note, when no background window is given", () => {
    const spec = powerlawSpec(1e10, 2.5);
    const r = integrateEdge(spec, SIGNAL)!;
    expect(r.net).toBe(r.gross);
    expect(r.background_counts).toBe(0);
    expect(r.note).toMatch(/no background window/);
  });

  it("degrades to a noted direct sum when the fit window has < 2 channels", () => {
    const spec = powerlawSpec(1e10, 2.5);
    const r = integrateEdge(spec, SIGNAL, { lo: 400, hi: 401 })!;
    expect(r.net).toBe(r.gross);
    expect(r.note).toMatch(/< 2 channels/);
  });

  it("returns null when the signal window holds no channels", () => {
    expect(integrateEdge(powerlawSpec(1e10, 2.5), { lo: 2000, hi: 2100 }, BG)).toBeNull();
  });

  it("normalises an inverted signal window", () => {
    const spec = powerlawSpec(1e10, 2.5);
    const fwd = integrateEdge(spec, SIGNAL, BG)!;
    const rev = integrateEdge(spec, { lo: SIGNAL.hi, hi: SIGNAL.lo }, BG)!;
    expect(rev.net).toBe(fwd.net);
    expect(rev.signal).toEqual(fwd.signal);
  });

  it("reports a σ that includes the fit uncertainty and improves with counts", () => {
    const dim = withBox(powerlawSpec(1e6, 2.5), SIGNAL.lo, SIGNAL.hi, 5);
    const bright = withBox(powerlawSpec(1e8, 2.5), SIGNAL.lo, SIGNAL.hi, 500);
    const rd = integrateEdge(dim, SIGNAL, BG)!;
    const rb = integrateEdge(bright, SIGNAL, BG)!;
    expect(rd.sigma).toBeGreaterThanOrEqual(Math.sqrt(rd.gross));
    // 100× the counts → the relative uncertainty must shrink (≈ √100)
    expect(rb.sigma / rb.net).toBeLessThan(rd.sigma / rd.net);
  });

  it("does not clamp a negative net — an over-subtracted window is information", () => {
    // Counts DIP below the continuum inside the signal window.
    const spec = withBox(powerlawSpec(1e10, 2.5), SIGNAL.lo, SIGNAL.hi, -100);
    const r = integrateEdge(spec, SIGNAL, BG)!;
    expect(r.net).toBeLessThan(0);
  });
});
