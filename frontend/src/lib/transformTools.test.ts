// TRANSFORM_TOOLS (GUI v2 Tools panel): catalogue completeness, group
// partitioning, fuzzy filtering, and the BATCH_FILTERS subset that feeds
// Image ▸ Batch Apply (must equal the legacy FILTER_DEFS set).

import { describe, expect, it } from "vitest";

import { fuzzy } from "./fuzzy";
import { validateParams } from "./params";
import {
  BATCH_FILTERS,
  TRANSFORM_GROUPS,
  TRANSFORM_TOOLS,
} from "./transformTools";

describe("TRANSFORM_TOOLS", () => {
  it("lists 18 tools, each kind exactly once, with label + glyph", () => {
    expect(TRANSFORM_TOOLS).toHaveLength(18);
    const kinds = TRANSFORM_TOOLS.map((t) => t.kind);
    expect(new Set(kinds).size).toBe(18);
    const expected = [
      "gaussian", "median", "unsharp", "butterworth", "clahe", "bin",
      "plane_level", "row_level", "scar_removal", "zero_level", "rotate90", "rotate270", "rotate180", "fliph",
      "flipv", "crop", "morph", "multiotsu",
    ];
    expect([...kinds].sort()).toEqual([...expected].sort());
    for (const t of TRANSFORM_TOOLS) {
      expect(t.label.length).toBeGreaterThan(0);
      expect(t.glyph.length).toBeGreaterThan(0);
    }
  });

  it("partitions tools into Filters / Level & Correct / Transform Image / Segment (6 / 4 / 6 / 2)", () => {
    expect(TRANSFORM_GROUPS).toEqual(["Filters", "Level & Correct", "Transform Image", "Segment"]);
    const counts = TRANSFORM_GROUPS.map(
      (g) => TRANSFORM_TOOLS.filter((t) => t.group === g).length,
    );
    expect(counts).toEqual([6, 4, 6, 2]);
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
    expect(byKind("plane_level").fields?.map((f) => f.key)).toEqual(["order", "fit_percentile"]);
    expect(byKind("row_level").fields?.map((f) => f.key)).toEqual(["method", "order", "fit_percentile"]);
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
  it("equals the legacy FILTER_DEFS set + the AFM levelling tools", () => {
    expect(BATCH_FILTERS).toHaveLength(15);
    expect(BATCH_FILTERS[0].label).toBe("Gaussian Blur"); // batch default
    const kinds = BATCH_FILTERS.map((d) => d.kind);
    expect([...kinds].sort()).toEqual(
      [
        "gaussian", "median", "unsharp", "butterworth", "clahe", "bin",
        "plane_level", "morph", "multiotsu", "rotate90", "fliph", "flipv",
        "row_level", "scar_removal", "zero_level",
      ].sort(),
    );
    // crop and the extra rotations stay out of batch (need an ROI / rare)
    expect(kinds).not.toContain("crop");
    expect(kinds).not.toContain("rotate180");
    expect(kinds).not.toContain("rotate270");
  });
});

describe("filter field bounds", () => {
  const fields = (kind: string) =>
    TRANSFORM_TOOLS.find((t) => t.kind === kind)?.fields ?? [];

  it("refuses out-of-range values before they reach the backend", () => {
    expect(validateParams({ sigma: "1e9" }, fields("gaussian"))).toMatch(/at most/);
    expect(validateParams({ sigma: "0" }, fields("gaussian"))).toMatch(/greater than 0/);
    expect(validateParams({ sigma: "-1" }, fields("unsharp"))).toMatch(/greater than 0/);
    expect(validateParams({ num_bins: "1e9" }, fields("clahe"))).toMatch(/at most/);
    expect(validateParams({ num_bins: "0" }, fields("clahe"))).toMatch(/at least/);
    expect(validateParams({ bin_size: "0" }, fields("bin"))).toMatch(/at least/);
    expect(validateParams({ bin_size: "-1" }, fields("bin"))).toMatch(/at least/);
    expect(validateParams({ radius: "1e9" }, fields("morph"))).toMatch(/at most/);
    expect(validateParams({ radius: "-1" }, fields("morph"))).toMatch(/at least/);
    expect(validateParams({ sigma: "2" }, fields("gaussian"))).toBeNull();
    expect(validateParams({ fit_percentile: "0" }, fields("plane_level"))).toMatch(/at least/);
    expect(validateParams({ max_width: "99" }, fields("scar_removal"))).toMatch(/at most/);
  });
});
