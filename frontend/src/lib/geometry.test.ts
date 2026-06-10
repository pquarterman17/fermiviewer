// geometry.ts — pure math shared by overlay labels, stats, and log.
// tiltDist MUST mirror calc/profiles.measure_distance (the backend
// test pins 16/sin30°=32; we pin the same cases client-side).

import { describe, expect, it } from "vitest";

import {
  boxProfileLine,
  niceScaleLength,
  physAngle,
  physDist,
  tiltDist,
  unitToNm,
  type TiltSettings,
} from "./geometry";

const P = (x: number, y: number) => ({ x, y });

describe("physDist", () => {
  it("3-4-5 triangle, uncalibrated → px", () => {
    expect(physDist(P(0, 0), P(3, 4), null)).toEqual({ value: 5, unit: "px" });
  });

  it("calibrated multiplies by pixel size", () => {
    expect(physDist(P(0, 0), P(3, 4), 0.5)).toEqual({
      value: 2.5,
      unit: "cal",
    });
  });

  it("zero-length is 0", () => {
    expect(physDist(P(7, 7), P(7, 7), null).value).toBe(0);
  });
});

describe("physAngle", () => {
  it("right angle", () => {
    expect(physAngle(P(0, 0), P(1, 0), P(0, 1))).toBeCloseTo(90, 10);
  });

  it("collinear opposite rays → 180", () => {
    expect(physAngle(P(0, 0), P(-1, 0), P(1, 0))).toBeCloseTo(180, 10);
  });

  it("reflex angles wrap into [0, 180]", () => {
    // rays at +170° and −170° are 20° apart, not 340°
    const a = P(Math.cos((170 * Math.PI) / 180), Math.sin((170 * Math.PI) / 180));
    const b = P(Math.cos((-170 * Math.PI) / 180), Math.sin((-170 * Math.PI) / 180));
    expect(physAngle(P(0, 0), a, b)).toBeCloseTo(20, 10);
  });
});

describe("tiltDist (#34 — mirrors calc/profiles.measure_distance)", () => {
  const cs = (angle: number, axis: "X" | "Y" = "Y"): TiltSettings => ({
    angle,
    axis,
    geometry: "cross-section",
  });

  it("null tilt === physDist", () => {
    expect(tiltDist(P(0, 0), P(3, 4), null, null)).toEqual(
      physDist(P(0, 0), P(3, 4), null),
    );
  });

  it("angle 0 is off (no 1/sin(0) blow-up)", () => {
    expect(tiltDist(P(0, 0), P(0, 10), null, cs(0)).value).toBe(10);
  });

  it("cross-section Y at 30°: vertical 10 px → 20 (matches backend doctest)", () => {
    expect(tiltDist(P(0, 0), P(0, 10), null, cs(30)).value).toBeCloseTo(20, 9);
  });

  it("in-axis only: horizontal line unaffected by Y-axis tilt", () => {
    expect(tiltDist(P(0, 0), P(10, 0), null, cs(30)).value).toBeCloseTo(10, 9);
  });

  it("axis X scales the x component", () => {
    expect(tiltDist(P(0, 0), P(10, 0), null, cs(30, "X")).value).toBeCloseTo(
      20,
      9,
    );
  });

  it("surface geometry uses 1/cos θ", () => {
    const t: TiltSettings = { angle: 60, axis: "Y", geometry: "surface" };
    expect(tiltDist(P(0, 0), P(0, 10), null, t).value).toBeCloseTo(20, 9);
  });

  it("negative angle is equivalent (component is squared)", () => {
    expect(tiltDist(P(0, 0), P(0, 10), null, cs(-30)).value).toBeCloseTo(
      20,
      9,
    );
  });

  it("mixed components: only in-axis part scales", () => {
    // dx=3 untouched, dy=4 → 8 at 30° cross-section: √(9+64)
    expect(tiltDist(P(0, 0), P(3, 4), null, cs(30)).value).toBeCloseTo(
      Math.sqrt(73),
      9,
    );
  });

  it("calibration applies after correction", () => {
    const d = tiltDist(P(0, 0), P(0, 10), 0.5, cs(30));
    expect(d.unit).toBe("cal");
    expect(d.value).toBeCloseTo(10, 9); // 20 px × 0.5 nm/px
  });
});

describe("boxProfileLine (box-profile capture)", () => {
  it("wide box → horizontal centerline, width = short (vertical) side", () => {
    const r = boxProfileLine(P(10, 20), P(110, 60));
    expect(r).toEqual({
      p0: { x: 10, y: 40 },
      p1: { x: 110, y: 40 },
      width: 40,
    });
  });

  it("tall box → vertical centerline, width = horizontal side", () => {
    const r = boxProfileLine(P(10, 20), P(40, 220));
    expect(r).toEqual({
      p0: { x: 25, y: 20 },
      p1: { x: 25, y: 220 },
      width: 30,
    });
  });

  it("drag direction does not matter", () => {
    expect(boxProfileLine(P(110, 60), P(10, 20))).toEqual(
      boxProfileLine(P(10, 20), P(110, 60)),
    );
  });

  it("degenerate boxes return null", () => {
    expect(boxProfileLine(P(0, 0), P(100, 1))).toBeNull();
    expect(boxProfileLine(P(0, 0), P(1, 100))).toBeNull();
  });

  it("width is rounded and at least 1", () => {
    const r = boxProfileLine(P(0, 0), P(50, 2.4));
    expect(r!.width).toBe(2);
  });
});

describe("unitToNm (scale-bar unit dropdown)", () => {
  it("converts the three offered units", () => {
    expect(unitToNm("Å")).toBe(0.1);
    expect(unitToNm("nm")).toBe(1);
    expect(unitToNm("µm")).toBe(1000);
  });

  it("tolerates ASCII spellings and case", () => {
    expect(unitToNm("A")).toBe(0.1);
    expect(unitToNm("angstrom")).toBe(0.1);
    expect(unitToNm("um")).toBe(1000);
    expect(unitToNm(" NM ")).toBe(1);
  });

  it("returns null for non-length calibrations", () => {
    expect(unitToNm("1/nm")).toBeNull();
    expect(unitToNm("px")).toBeNull();
    expect(unitToNm("")).toBeNull();
  });
});

describe("niceScaleLength", () => {
  it("picks the largest 1/2/5×10ⁿ below max", () => {
    expect(niceScaleLength(7)).toBe(5);
    expect(niceScaleLength(43)).toBe(20);
    expect(niceScaleLength(100)).toBe(100);
    expect(niceScaleLength(0.3)).toBe(0.2);
  });
});
