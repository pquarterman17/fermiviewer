import { describe, expect, it } from "vitest";

import { figureColumns, figureScaleBar } from "./figureExport";
import { legendDetail } from "./mapLegend";
import { tileKey, tileLabel, type MapTile } from "./mapTile";

const tile = (over: Partial<MapTile> = {}): MapTile => ({
  symbol: "Fe",
  line: "K",
  map: [
    [1, 2],
    [3, 4],
  ],
  shape: [2, 2],
  totalCounts: 4200,
  ...over,
});

describe("figureScaleBar", () => {
  it("picks a round length under 40 % of the field of view", () => {
    // 128 scan pixels × 10 nm = 1280 nm across; 40 % of that is 512 nm, and
    // the largest 1/2/5×10ⁿ below it is 500.
    const bar = figureScaleBar(128, 10, "nm");
    expect(bar).toEqual({ fraction: 500 / 1280, label: "500 nm" });
  });

  it("steps a sub-nanometre bar down to ångströms", () => {
    const bar = figureScaleBar(100, 0.005, "nm"); // 0.5 nm across
    expect(bar?.label).toBe("2 Å");
    expect(bar?.fraction).toBeCloseTo(0.4, 10);
  });

  it("never spans more than 40 % of the tile, at any scale", () => {
    for (const px of [0.001, 0.017, 1, 3.7, 1000]) {
      for (const w of [8, 33, 128, 512]) {
        const bar = figureScaleBar(w, px, "nm");
        expect(bar).toBeDefined();
        expect(bar!.fraction).toBeGreaterThan(0);
        expect(bar!.fraction).toBeLessThanOrEqual(0.4);
      }
    }
  });

  it("draws no bar rather than a made-up one on an uncalibrated cube", () => {
    // A bar is an assertion about physical length. Absent calibration there
    // is nothing to assert, and a default-1-px/unit bar would be a lie.
    expect(figureScaleBar(128, null, "nm")).toBeUndefined();
    expect(figureScaleBar(128, undefined, "nm")).toBeUndefined();
    expect(figureScaleBar(128, 0, "nm")).toBeUndefined();
    expect(figureScaleBar(128, -4, "nm")).toBeUndefined();
    expect(figureScaleBar(128, Number.NaN, "nm")).toBeUndefined();
    expect(figureScaleBar(128, 10, "")).toBeUndefined();
    expect(figureScaleBar(128, 10, undefined)).toBeUndefined();
    expect(figureScaleBar(0, 10, "nm")).toBeUndefined();
  });
});

describe("figureColumns", () => {
  it("counts the overlay as a panel", () => {
    expect(figureColumns(3, true)).toBe(2); // 4 panels → 2×2
    expect(figureColumns(3, false)).toBe(2); // 3 panels → 2 wide
    expect(figureColumns(8, true)).toBe(3); // 9 panels → 3×3
  });

  it("stays between 2 and 4 columns", () => {
    expect(figureColumns(1, false)).toBe(2);
    expect(figureColumns(40, true)).toBe(4);
  });
});

describe("legendDetail", () => {
  it("reports net counts, at%, or nothing, per the legend selection", () => {
    const fe = tile();
    expect(legendDetail(fe, "none")).toBe("");
    expect(legendDetail(fe, "net")).toBe("4.2k");
    expect(legendDetail(fe, "atomic", { Fe: 33.21 })).toBe("33.2 at%");
  });

  it("says nothing rather than 0 at% for an unquantified element", () => {
    expect(legendDetail(tile(), "atomic", { Cu: 12 })).toBe("");
    expect(legendDetail(tile(), "atomic")).toBe("");
  });

  it("shares one at% between an element's two EELS edges", () => {
    const k = tile({ symbol: "Si", line: "K", caption: "Si K" });
    const l = tile({ symbol: "Si", line: "L23", caption: "Si L23" });
    const quant = { Si: 40 };
    expect(legendDetail(k, "atomic", quant)).toBe("40.0 at%");
    expect(legendDetail(l, "atomic", quant)).toBe("40.0 at%");
    // ...while their keys and labels stay distinct
    expect(tileKey(k)).not.toBe(tileKey(l));
    expect(tileLabel(k)).toBe("Si K");
  });
});

describe("tileLabel", () => {
  it("appends the EDS α only when no caption overrides it", () => {
    expect(tileLabel(tile())).toBe("Fe Kα");
    expect(tileLabel(tile({ caption: "Fe L2,3" }))).toBe("Fe L2,3");
  });
});
