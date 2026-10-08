// coerceParams: numeric-string coercion shared by ParamDialog (menu
// commands) and TransformPanel (inline tool params). The 0-preservation
// case is the one that bit us — `Number(v) || default` silently dropped a
// valid typed 0 to the field default.

import { describe, expect, it } from "vitest";

import { coerceParams, validateParams, type ParamField } from "./params";

const numField = (key: string, dflt: number): ParamField => ({
  key,
  label: key,
  type: "number",
  default: dflt,
});

describe("coerceParams", () => {
  it("preserves a typed 0 instead of falling back to the default", () => {
    // regression: 0 is falsy, so `Number("0") || 2` wrongly returned 2
    expect(coerceParams({ x: "0" }, [numField("x", 2)])).toEqual({ x: 0 });
  });

  it("falls back to the field default for a key missing from values entirely", () => {
    // Ported from quantized's params.test.ts (2026-08-05): the last
    // chokepoint before a command consumes the result must always have
    // every field's key, even when `values` itself is partial (the shape a
    // ParamDialog render race can otherwise hand to a consumer that does
    // `(params.x as string).trim()` with no guard of its own).
    const fields: ParamField[] = [numField("x", 2), numField("y", 9)];
    expect(coerceParams({ x: "5" }, fields)).toEqual({ x: 5, y: 9 });
    expect(coerceParams({}, fields)).toEqual({ x: 2, y: 9 });
  });

  it("coerces numeric strings to numbers", () => {
    expect(coerceParams({ x: "5" }, [numField("x", 2)])).toEqual({ x: 5 });
    expect(coerceParams({ x: "0.05" }, [numField("x", 2)])).toEqual({ x: 0.05 });
  });

  it("falls back to the default for non-numeric input", () => {
    expect(coerceParams({ x: "abc" }, [numField("x", 2)])).toEqual({ x: 2 });
  });

  it("passes through already-numeric values untouched", () => {
    expect(coerceParams({ x: 3 }, [numField("x", 2)])).toEqual({ x: 3 });
    expect(coerceParams({ x: 0 }, [numField("x", 2)])).toEqual({ x: 0 });
  });

  it("leaves non-number fields untouched", () => {
    const fields: ParamField[] = [
      { key: "op", label: "Op", type: "select", default: "open", options: ["open", "close"] },
      { key: "save", label: "Save", type: "boolean", default: false },
      { key: "name", label: "Name", type: "text", default: "" },
    ];
    expect(
      coerceParams({ op: "close", save: true, name: "frame" }, fields),
    ).toEqual({ op: "close", save: true, name: "frame" });
  });
});

describe("coerceParams bounds", () => {
  const f = [{ key: "g", label: "g", type: "number" as const, default: 4, min: 0, max: 64, int: true }];
  it("clamps and rounds typed strings and numbers", () => {
    expect(coerceParams({ g: "100" }, f).g).toBe(64);
    expect(coerceParams({ g: -3 }, f).g).toBe(0);
    expect(coerceParams({ g: "2.6" }, f).g).toBe(3);
    expect(coerceParams({ g: "abc" }, f).g).toBe(4);
  });
});

describe("validateParams", () => {
  const len = { key: "len", label: "Length", type: "number" as const, default: 1, positive: true, max: 1e9 };
  const gap = { key: "g", label: "Gap", type: "number" as const, default: 4, min: 0, max: 64, int: true };
  it("refuses non-numbers instead of substituting the default", () => {
    expect(validateParams({ len: "abc" }, [len])).toMatch(/enter a number/);
    expect(validateParams({ len: "" }, [len])).toMatch(/enter a number/);
  });
  it("checks positive, range and whole-number bounds", () => {
    expect(validateParams({ len: 0 }, [len])).toMatch(/greater than 0/);
    expect(validateParams({ len: "1e300" }, [len])).toMatch(/at most/);
    expect(validateParams({ g: 2.5 }, [gap])).toMatch(/whole number/);
    expect(validateParams({ g: -1 }, [gap])).toMatch(/at least 0/);
  });
  it("accepts valid input and untouched defaults", () => {
    expect(validateParams({ len: "343.8", g: 4 }, [len, gap])).toBeNull();
    expect(validateParams({}, [len, gap])).toBeNull();
  });
});
