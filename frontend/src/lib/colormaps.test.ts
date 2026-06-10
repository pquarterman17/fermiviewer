// colormaps.ts — LUT construction + custom-cmap parsing. The backend
// mirror (calc/colormaps.py) must stay in sync with these stops; the
// endpoints tested here are the frontend's contract.

import { describe, expect, it } from "vitest";

import { buildLut, setCustomColormap } from "./colormaps";

describe("buildLut", () => {
  it("gray is an identity ramp with opaque alpha", () => {
    const lut = buildLut("gray");
    expect(lut.length).toBe(256 * 4);
    expect([lut[0], lut[1], lut[2], lut[3]]).toEqual([0, 0, 0, 255]);
    const last = 255 * 4;
    expect([lut[last], lut[last + 1], lut[last + 2]]).toEqual([
      255, 255, 255,
    ]);
    // monotone non-decreasing red channel
    for (let i = 1; i < 256; i++) {
      expect(lut[i * 4]).toBeGreaterThanOrEqual(lut[(i - 1) * 4]);
    }
  });

  it("invert runs white → black", () => {
    const lut = buildLut("invert");
    expect(lut[0]).toBe(255);
    expect(lut[255 * 4]).toBe(0);
  });

  it("custom without stored stops falls back to gray", () => {
    expect(Array.from(buildLut("custom"))).toEqual(
      Array.from(buildLut("gray")),
    );
  });
});

describe("setCustomColormap", () => {
  it("parses 3- and 6-digit hex stops and stores them", () => {
    expect(setCustomColormap("#000, #a070f0, #fff")).toBe(true);
    const lut = buildLut("custom");
    expect([lut[0], lut[1], lut[2]]).toEqual([0, 0, 0]);
    const mid = 128 * 4; // t≈0.5 lands on the middle stop
    expect(lut[mid]).toBeGreaterThan(0x90);
    expect(lut[mid]).toBeLessThan(0xb0);
    expect(lut[255 * 4]).toBe(255);
  });

  it("rejects fewer than 2 valid stops and stores nothing", () => {
    expect(setCustomColormap("#abc")).toBe(false);
    expect(setCustomColormap("garbage, more garbage")).toBe(false);
    expect(localStorage.getItem("fv_custom_cmap")).toBeNull();
  });

  it("skips unparseable entries but keeps valid ones", () => {
    expect(setCustomColormap("#000, nope, #ffffff")).toBe(true);
  });
});
