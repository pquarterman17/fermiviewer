// lengthUnits.ts — measure display-unit conversion (owner-approved
// design). Pins the two literal owner examples, the squared-vs-linear
// area trap, the Auto 0.01 boundary, reciprocal/unrecognized rejection,
// and unit-spelling equivalence.

import { describe, expect, it } from "vitest";

import { displayArea, displayLength, linearUnitToNm } from "./lengthUnits";

describe("linearUnitToNm", () => {
  it("parses the canonical spellings", () => {
    expect(linearUnitToNm("nm")).toBe(1);
    expect(linearUnitToNm("um")).toBe(1000);
    expect(linearUnitToNm("µm")).toBe(1000);
    expect(linearUnitToNm("mm")).toBe(1e6);
    expect(linearUnitToNm("A")).toBeCloseTo(0.1);
    expect(linearUnitToNm("Å")).toBeCloseTo(0.1);
  });

  it("'um' and 'µm' parse identically (ASCII vs micro-sign spelling)", () => {
    expect(linearUnitToNm("um")).toBe(linearUnitToNm("µm"));
  });

  it("'A' and 'Å' parse identically (ASCII vs angstrom-glyph spelling)", () => {
    expect(linearUnitToNm("A")).toBe(linearUnitToNm("Å"));
  });

  it("accepts 'angstrom' and is case-insensitive", () => {
    expect(linearUnitToNm("angstrom")).toBeCloseTo(0.1);
    expect(linearUnitToNm("ANGSTROM")).toBeCloseTo(0.1);
    expect(linearUnitToNm("NM")).toBe(1);
    expect(linearUnitToNm("MM")).toBe(1e6);
  });

  it("rejects a reciprocal (diffraction) calibration unit — never 'converted'", () => {
    expect(linearUnitToNm("1/nm")).toBeNull();
  });

  it("rejects uncalibrated px", () => {
    expect(linearUnitToNm("px")).toBeNull();
  });

  it("rejects empty and unrecognized strings", () => {
    expect(linearUnitToNm("")).toBeNull();
    expect(linearUnitToNm("furlong")).toBeNull();
  });
});

describe("displayLength — owner example", () => {
  it("850 nm + Auto -> 0.85 µm", () => {
    expect(displayLength(850, "nm", "auto")).toEqual({ value: 0.85, unit: "µm" });
  });
});

describe("displayArea — owner example", () => {
  it("37990 nm² + Auto -> 0.038 µm²", () => {
    expect(displayArea(37990, "nm", "auto")).toEqual({ value: 0.038, unit: "µm²" });
  });
});

describe("displayArea — squared-factor trap", () => {
  it("uses the SQUARED nm->µm factor (1e6), not the linear one (1e3)", () => {
    // 5,000,000 nm^2 -> correct (÷1e6) is 5 µm^2. A buggy implementation
    // that reused the LINEAR length factor (÷1e3) would report 5000 —
    // wrong by exactly 1000x. Mutation: change the area factor from
    // `f*f` to `f` in displayArea and this assertion goes RED (5000
    // instead of 5).
    expect(displayArea(5_000_000, "nm", "um")).toEqual({ value: 5, unit: "µm²" });
  });
});

describe("displayLength — Auto 0.01 boundary", () => {
  it("a value landing EXACTLY at 0.01 of the next unit chooses the larger unit", () => {
    // 10 nm -> 0.01 µm exactly. Mutation: >= -> > flips this to "nm".
    expect(displayLength(10, "nm", "auto")).toEqual({ value: 0.01, unit: "µm" });
  });

  it("a value just below the 0.01 threshold stays in the smaller unit", () => {
    // 9.9 nm -> 0.0099 µm, just under 0.01 -> stays nm.
    expect(displayLength(9.9, "nm", "auto")).toEqual({ value: 9.9, unit: "nm" });
  });
});

describe("displayLength/displayArea — reciprocal calibration disables conversion", () => {
  it("returns null for '1/nm' regardless of choice", () => {
    expect(displayLength(850, "1/nm", "auto")).toBeNull();
    expect(displayLength(850, "1/nm", "nm")).toBeNull();
    expect(displayArea(37990, "1/nm", "auto")).toBeNull();
  });

  it("returns null for uncalibrated px", () => {
    expect(displayLength(850, "px", "auto")).toBeNull();
    expect(displayArea(37990, "px", "auto")).toBeNull();
  });
});

describe("displayLength/displayArea — Auto at value 0", () => {
  it("renders null (caller falls back to the calibration unit) rather than fabricating '0 Å'", () => {
    expect(displayLength(0, "nm", "auto")).toBeNull();
    expect(displayArea(0, "nm", "auto")).toBeNull();
  });

  it("an EXPLICIT unit choice still converts 0 (only Auto special-cases zero)", () => {
    expect(displayLength(0, "nm", "um")).toEqual({ value: 0, unit: "µm" });
  });
});

describe("displayLength — fixed unit choices", () => {
  it("converts nm calibration to a fixed Å choice", () => {
    expect(displayLength(2, "nm", "A")).toEqual({ value: 20, unit: "Å" });
  });

  it("converts µm calibration to a fixed mm choice", () => {
    expect(displayLength(1500, "um", "mm")).toEqual({ value: 1.5, unit: "mm" });
  });
});
