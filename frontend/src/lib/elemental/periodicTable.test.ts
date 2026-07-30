import { describe, expect, it } from "vitest";

import { ALL_ELEMENTS, PERIODIC_GRID } from "./periodicTable";

describe("periodic table layout", () => {
  it("contains the common EDS elements", () => {
    for (const s of ["Si", "Fe", "Al", "O", "Cu", "Ti", "Au", "U"]) {
      expect(ALL_ELEMENTS).toContain(s);
    }
  });

  it("keeps every render row exactly 18 cells wide", () => {
    for (const row of PERIODIC_GRID) expect(row).toHaveLength(18);
  });

  it("has no duplicate symbols", () => {
    expect(new Set(ALL_ELEMENTS).size).toBe(ALL_ELEMENTS.length);
  });
});
