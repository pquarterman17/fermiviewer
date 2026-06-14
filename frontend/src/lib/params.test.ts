// coerceParams: numeric-string coercion shared by ParamDialog (menu
// commands) and TransformPanel (inline tool params). The 0-preservation
// case is the one that bit us — `Number(v) || default` silently dropped a
// valid typed 0 to the field default.

import { describe, expect, it } from "vitest";

import { coerceParams, type ParamField } from "./params";

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
