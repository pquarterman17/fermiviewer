// TRANSFORM_TOOLS (GUI v2 Tools panel): catalogue completeness, group
// partitioning, fuzzy filtering, and the BATCH_FILTERS subset that feeds
// Image ▸ Batch Apply (must equal the legacy FILTER_DEFS set).

import { describe, expect, it } from "vitest";

import { fuzzy } from "./fuzzy";
import {
  BATCH_FILTERS,
  TRANSFORM_GROUPS,
  TRANSFORM_TOOLS,
} from "./transformTools";

describe("TRANSFORM_TOOLS", () => {
  it("lists 15 tools, each kind exactly once, with label + glyph", () => {
    expect(TRANSFORM_TOOLS).toHaveLength(15);
    const kinds = TRANSFORM_TOOLS.map((t) => t.kind);
    expect(new Set(kinds).size).toBe(15);
    const expected = [
      "gaussian", "median", "unsharp", "butterworth", "clahe", "bin",
      "plane_level", "rotate90", "rotate270", "rotate180", "fliph",
      "flipv", "crop", "morph", "multiotsu",
    ];
    expect([...kinds].sort()).toEqual([...expected].sort());
    for (const t of TRANSFORM_TOOLS) {
      expect(t.label.length).toBeGreaterThan(0);
      expect(t.glyph.length).toBeGreaterThan(0);
    }
  });

  it("partitions tools into Enhance / Geometry / Segment (7 / 6 / 2)", () => {
    expect(TRANSFORM_GROUPS).toEqual(["Enhance", "Geometry", "Segment"]);
    const counts = TRANSFORM_GROUPS.map(
      (g) => TRANSFORM_TOOLS.filter((t) => t.group === g).length,
    );
    expect(counts).toEqual([7, 6, 2]);
    for (const t of TRANSFORM_TOOLS) expect(TRANSFORM_GROUPS).toContain(t.group);
  });

  it("routes each tool via filter / geometry / crop correctly", () => {
    const byKind = (k: string) => TRANSFORM_TOOLS.find((t) => t.kind === k)!;
    expect(byKind("gaussian").via).toBe("filter");
    expect(byKind("rotate90").via).toBe("geometry");
    expect(byKind("crop").via).toBe("crop");
  });

  it("attaches parameter fields only where the op needs them", () => {
    const byKind = (k: string) => TRANSFORM_TOOLS.find((t) => t.kind === k)!;
    expect(byKind("gaussian").fields?.map((f) => f.key)).toEqual(["sigma"]);
    expect(byKind("plane_level").fields).toBeUndefined();
    expect(byKind("rotate90").fields).toBeUndefined();
    expect(byKind("morph").fields).toHaveLength(3);
  });

  it("fuzzy-filters labels the same way TransformPanel does", () => {
    const match = (query: string) =>
      TRANSFORM_TOOLS.filter((t) => fuzzy(query, t.label) !== null).map(
        (t) => t.kind,
      );
    expect(match("gauss")).toEqual(["gaussian"]);
    expect(match("rotate")).toEqual(["rotate90", "rotate270", "rotate180"]);
    expect(match("zzz")).toEqual([]);
  });
});

describe("BATCH_FILTERS", () => {
  it("equals the legacy FILTER_DEFS set: 9 filters + rotate90/fliph/flipv", () => {
    expect(BATCH_FILTERS).toHaveLength(12);
    expect(BATCH_FILTERS[0].label).toBe("Gaussian Blur"); // batch default
    const kinds = BATCH_FILTERS.map((d) => d.kind);
    expect([...kinds].sort()).toEqual(
      [
        "gaussian", "median", "unsharp", "butterworth", "clahe", "bin",
        "plane_level", "morph", "multiotsu", "rotate90", "fliph", "flipv",
      ].sort(),
    );
    // crop and the extra rotations stay out of batch (need an ROI / rare)
    expect(kinds).not.toContain("crop");
    expect(kinds).not.toContain("rotate180");
    expect(kinds).not.toContain("rotate270");
  });
});
