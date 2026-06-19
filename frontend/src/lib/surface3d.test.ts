import { describe, expect, it } from "vitest";

import {
  DEFAULT_AZ,
  DEFAULT_EL,
  clampEl,
  dragToOrbit,
  normaliseAz,
  project,
} from "./surface3d";

describe("normaliseAz", () => {
  it("keeps values already in range unchanged", () => {
    expect(normaliseAz(0)).toBeCloseTo(0);
    expect(normaliseAz(90)).toBeCloseTo(90);
    expect(normaliseAz(-90)).toBeCloseTo(-90);
  });

  it("wraps values outside (−180, 180]", () => {
    expect(normaliseAz(270)).toBeCloseTo(-90);
    expect(normaliseAz(-270)).toBeCloseTo(90);
    expect(normaliseAz(360)).toBeCloseTo(0);
    expect(normaliseAz(181)).toBeCloseTo(-179);
  });
});

describe("clampEl", () => {
  it("passes through in-range values", () => {
    expect(clampEl(0)).toBe(0);
    expect(clampEl(30)).toBe(30);
    expect(clampEl(-45)).toBe(-45);
  });

  it("clamps to [−89, 89]", () => {
    expect(clampEl(100)).toBe(89);
    expect(clampEl(-100)).toBe(-89);
  });
});

describe("dragToOrbit", () => {
  it("maps dx to positive dAz and dy to negative dEl", () => {
    const { dAz, dEl } = dragToOrbit(10, 5);
    expect(dAz).toBeGreaterThan(0);
    expect(dEl).toBeLessThan(0);
  });

  it("zero input gives zero deltas", () => {
    const { dAz, dEl } = dragToOrbit(0, 0);
    expect(dAz).toBeCloseTo(0);
    expect(dEl).toBeCloseTo(0);
  });
});

describe("project", () => {
  const W = 320;
  const H = 260;

  it("centre of unit cube maps close to canvas centre", () => {
    const { sx, sy } = project(0.5, 0.5, 0.5, DEFAULT_AZ, DEFAULT_EL, W, H, 10);
    expect(sx).toBeCloseTo(W / 2, 0);
    expect(sy).toBeCloseTo(H / 2, 0);
  });

  it("returns finite values for all corners of the unit cube", () => {
    for (const u of [0, 1]) {
      for (const v of [0, 1]) {
        for (const w of [0, 1]) {
          const { sx, sy } = project(u, v, w, DEFAULT_AZ, DEFAULT_EL, W, H, 10);
          expect(Number.isFinite(sx)).toBe(true);
          expect(Number.isFinite(sy)).toBe(true);
        }
      }
    }
  });

  it("different az values produce different x positions for a non-central point", () => {
    const p1 = project(1, 0, 0, 0, 0, W, H, 10);
    const p2 = project(1, 0, 0, 90, 0, W, H, 10);
    expect(Math.abs(p1.sx - p2.sx)).toBeGreaterThan(1);
  });

  it("higher elevation raises the projected y (lowers sy on canvas)", () => {
    const lo = project(0.5, 0.5, 1, DEFAULT_AZ, 10, W, H, 10);
    const hi = project(0.5, 0.5, 1, DEFAULT_AZ, 70, W, H, 10);
    // At higher elevation the top of the surface appears higher on screen (smaller sy)
    expect(hi.sy).toBeLessThan(lo.sy);
  });
});
