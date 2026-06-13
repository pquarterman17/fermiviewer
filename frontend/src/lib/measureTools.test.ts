// MEASURE_TOOLS (GUI v2 measure command list): catalogue completeness,
// group partitioning, and fuzzy-filter behaviour shared with MeasurePanel.

import { describe, expect, it } from "vitest";

import { fuzzy } from "./fuzzy";
import { MEASURE_GROUPS, MEASURE_TOOLS } from "./measureTools";

describe("MEASURE_TOOLS", () => {
  it("lists 11 capture kinds, each exactly once", () => {
    expect(MEASURE_TOOLS).toHaveLength(11);
    const kinds = MEASURE_TOOLS.map((t) => t.kind);
    expect(new Set(kinds).size).toBe(11);
    const expected = [
      "profile",
      "box-profile",
      "distance",
      "angle",
      "polyline",
      "roi",
      "ellipse",
      "text",
      "arrow",
      "box",
      "circle",
    ];
    expect([...kinds].sort()).toEqual([...expected].sort());
  });

  it("partitions tools into groups of 5 / 2 / 4 in order", () => {
    expect(MEASURE_GROUPS).toEqual([
      "Profiles & Distance",
      "Regions of Interest",
      "Annotations",
    ]);
    const counts = MEASURE_GROUPS.map(
      (g) => MEASURE_TOOLS.filter((t) => t.group === g).length,
    );
    expect(counts).toEqual([5, 2, 4]);
    for (const t of MEASURE_TOOLS) expect(MEASURE_GROUPS).toContain(t.group);
  });

  it("fuzzy-filters labels the same way MeasurePanel does", () => {
    const match = (query: string) =>
      MEASURE_TOOLS.filter((t) => fuzzy(query, t.label) !== null).map(
        (t) => t.kind,
      );
    expect(match("dist")).toEqual(["distance"]);
    expect(match("prof")).toEqual(["profile", "box-profile"]);
    expect(match("zzz")).toEqual([]);
  });
});
