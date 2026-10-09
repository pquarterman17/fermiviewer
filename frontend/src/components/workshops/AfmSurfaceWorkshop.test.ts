// The ISO 25178 table: every parameter grouped once, units carried into
// the export rows, missing values shown as a dash.
import { describe, expect, it } from "vitest";

import { ISO_PARAMS, type AfmSurfaceResult } from "../../lib/api";
import { formatParam, ISO_GROUPS, surfaceRows } from "./AfmSurfaceWorkshop";

describe("AfmSurfaceWorkshop helpers", () => {
  it("groups every ISO parameter exactly once", () => {
    expect(ISO_GROUPS.flatMap((g) => g.keys).sort()).toEqual([...ISO_PARAMS].sort());
  });

  it("formats values with units and dashes for missing ones", () => {
    expect(formatParam(1.23456, "nm")).toBe("1.235 nm");
    expect(formatParam(null, "%")).toBe("—");
    expect(formatParam(0.5, "")).toBe("0.5000");
  });

  it("exports one row per parameter with its unit", () => {
    const params = Object.fromEntries(ISO_PARAMS.map((k) => [k, 1])) as AfmSurfaceResult["params"];
    const units = Object.fromEntries(ISO_PARAMS.map((k) => [k, k === "Sa" ? "nm" : ""])) as
      AfmSurfaceResult["units"];
    const rows = surfaceRows({ params, units } as AfmSurfaceResult);
    expect(rows).toHaveLength(ISO_PARAMS.length);
    expect(rows[0].slice(0, 3)).toEqual(["Sa", 1, "nm"]);
  });
});
