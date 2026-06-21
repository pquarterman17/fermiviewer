// colormaps.ts — LUT construction + custom-cmap parsing. The backend
// mirror (calc/colormaps.py) must stay in sync with these stops; the
// endpoints tested here are the frontend's contract.

import { describe, expect, it } from "vitest";

import {
  buildLabelLut,
  buildLut,
  labelColor,
  setCustomColormap,
} from "./colormaps";

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

describe("buildLabelLut / labelColor (discrete grain palette)", () => {
  it("label 0 is black; adjacent labels are coloured and distinct", () => {
    expect(labelColor(0)).toEqual([0, 0, 0]);
    expect(labelColor(1)).not.toEqual([0, 0, 0]);
    expect(labelColor(1)).not.toEqual(labelColor(2));
    expect(labelColor(2)).not.toEqual(labelColor(3));
  });

  it("each label id maps to its own flat band in the LUT", () => {
    const maxLabel = 4; // labels 0..4
    const lut = buildLabelLut(maxLabel + 1);
    expect(lut.length).toBe(256 * 4);
    for (let k = 0; k <= maxLabel; k++) {
      const i = Math.round((k / maxLabel) * 255) * 4;
      expect([lut[i], lut[i + 1], lut[i + 2]]).toEqual(labelColor(k));
    }
    expect([lut[0], lut[1], lut[2]]).toEqual([0, 0, 0]); // id 0 = black
  });

  it('buildLut("label") returns a discrete default cycle', () => {
    const lut = buildLut("label");
    expect(lut.length).toBe(256 * 4);
    expect([lut[0], lut[1], lut[2]]).toEqual([0, 0, 0]); // background black
  });
});
