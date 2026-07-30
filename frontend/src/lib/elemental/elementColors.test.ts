import { beforeEach, describe, expect, it } from "vitest";

import {
  buildElementLut,
  defaultElementColor,
  elementColor,
  isElementColorCustom,
  resetAllElementColors,
  setElementColor,
} from "./elementColors";

beforeEach(() => {
  resetAllElementColors();
});

describe("element colour registry", () => {
  it("gives every element a distinct default", () => {
    const symbols = ["C", "N", "O", "Si", "Fe", "Cr", "Ni", "Ga", "As", "Pu"];
    expect(new Set(symbols.map(defaultElementColor)).size).toBe(symbols.length);
  });

  it("resolves an override over the default and reports it as custom", () => {
    expect(isElementColorCustom("C")).toBe(false);
    setElementColor("C", "#00ff00");
    expect(elementColor("C")).toBe("#00ff00");
    expect(isElementColorCustom("C")).toBe(true);
    expect(elementColor("O")).toBe(defaultElementColor("O"));
  });

  it("ignores anything that is not a #rrggbb colour", () => {
    setElementColor("C", "green");
    setElementColor("C", "#0f0");
    expect(isElementColorCustom("C")).toBe(false);
  });

  it("restores defaults on reset", () => {
    setElementColor("Fe", "#123456");
    resetAllElementColors();
    expect(elementColor("Fe")).toBe(defaultElementColor("Fe"));
  });

  it("persists overrides so a reload keeps them", () => {
    setElementColor("Si", "#abcdef");
    const stored: unknown = JSON.parse(
      localStorage.getItem("fv_eds_element_colors") ?? "{}",
    );
    expect(stored).toEqual({ Si: "#abcdef" });
  });
});

describe("buildElementLut", () => {
  it("ramps black → element colour → white across 256 entries", () => {
    const lut = buildElementLut("#22c55e");
    expect(lut).toHaveLength(256 * 4);
    expect([lut[0], lut[1], lut[2]]).toEqual([0, 0, 0]);
    // top of the ramp lifts toward white so the hottest pixels stay separable
    expect([lut[1020], lut[1021], lut[1022]]).toEqual([255, 255, 255]);
    // the element's own colour sits at the ramp's knee
    const knee = Math.round(0.82 * 255) * 4;
    expect(lut[knee]).toBeCloseTo(0x22, -1);
    expect(lut[knee + 1]).toBeCloseTo(0xc5, -1);
    expect(lut[knee + 2]).toBeCloseTo(0x5e, -1);
    expect(lut[3]).toBe(255); // opaque
  });
});
