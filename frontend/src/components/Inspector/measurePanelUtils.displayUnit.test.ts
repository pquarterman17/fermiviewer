// measure display-units feature — showLog's per-row CSV value must never
// disagree with the stage label about WHICH converted number/unit a
// measure has (mandatory pin: "Panel/CSV consistency"). This cross-checks
// the two INDEPENDENT implementations (measureGlyphs.measureLabel vs.
// showLog's inline per-row builder) against each other rather than
// duplicating one expected string, so a copy/paste slip in either one
// would be caught.
//
// PR #159 critical-review fix 1 ("precision belongs to display sites, not
// the lib"): CSV and the stage label are no longer required to produce
// the byte-identical STRING for a value that needs rounding — the stage
// label rounds to 3 sig figs (readability, matches formatScaleLength);
// showLog deliberately keeps its own higher-precision 6-sig-fig format,
// because rounding a CSV export to label precision was exactly the bug
// this fix removes (1234.5 nm + 'um' used to export "1.23 µm", a 0.36%
// error). The two still agree exactly whenever no rounding is lossy
// (850 nm case below) — the divergence only shows up once the converted
// value has more than 3 significant figures (37990 nm² case below).

import { describe, expect, it } from "vitest";

import { measureLabel } from "../Stage/measureGlyphs";
import type { Measure } from "../../store/viewerTypes";
import { showLog } from "./measurePanelUtils";
import { useResults } from "../overlays/ResultsWindow";

const META = { pixel_size: 1, pixel_unit: "nm" };

function lastLoggedValue(): string {
  const table = useResults.getState().table;
  if (!table) throw new Error("showLog did not populate the Results table");
  return String(table.rows[0][2]);
}

describe("showLog CSV value === stage label (owner examples)", () => {
  it("850 nm distance + Auto: CSV row matches the on-canvas label ('0.85 µm')", () => {
    const img = { w: 1000, h: 1000 };
    const m: Measure = {
      id: "m1",
      kind: "distance",
      pts: [{ x: 0, y: 0 }, { x: 0.85, y: 0 }],
      displayUnit: "auto",
    };
    const label = measureLabel(m, {
      img,
      pixelSize: META.pixel_size,
      pixelUnit: META.pixel_unit,
      tilt: null,
      roiStats: {},
    });
    expect(label).toBe("0.85 µm");

    showLog([m], img, META, {}, null);
    expect(lastLoggedValue()).toBe(label);
  });

  it("37990 nm² polygon area + Auto: CSV keeps full precision (0.03799 µm²), the stage label still rounds to 3 sig figs (0.038 µm²)", () => {
    // The exact case the review flagged: 37990 nm² -> 0.03799 µm² has 4
    // significant figures, so the stage's 3-sig-fig round (0.038) and
    // the CSV's 6-sig-fig round (0.03799, unchanged since it already has
    // fewer than 6 sig figs) are now DIFFERENT strings on purpose — pre-
    // fix, the lib rounded to 3 sig figs before either site ever saw the
    // value, so both were forced to the SAME (lossy) 0.038.
    const img = { w: 3799, h: 10 };
    const m: Measure = {
      id: "m1",
      kind: "polygon",
      pts: [
        { x: 0, y: 0 },
        { x: 1, y: 0 },
        { x: 1, y: 1 },
        { x: 0, y: 1 },
      ],
      displayUnit: "auto",
    };
    const label = measureLabel(m, {
      img,
      pixelSize: META.pixel_size,
      pixelUnit: META.pixel_unit,
      tilt: null,
      roiStats: {},
    });
    expect(label).toBe("0.038 µm²");

    showLog([m], img, META, {}, null);
    expect(lastLoggedValue()).toBe("0.03799 µm²");
    expect(lastLoggedValue()).not.toBe(label);
  });

  it("1234.5 nm distance + 'um' override: CSV exports 1.2345 µm at full precision, not the label's rounded 1.23 µm (PR #159 review fix 1)", () => {
    const img = { w: 2469, h: 1 };
    const m: Measure = {
      id: "m1",
      kind: "distance",
      // 0.5 * 2469 image-px = 1234.5 px, pixel_size 1 nm/px -> 1234.5 nm
      pts: [{ x: 0, y: 0 }, { x: 0.5, y: 0 }],
      displayUnit: "um",
    };
    const label = measureLabel(m, {
      img,
      pixelSize: META.pixel_size,
      pixelUnit: META.pixel_unit,
      tilt: null,
      roiStats: {},
    });
    expect(label).toBe("1.23 µm"); // label rounds to 3 sig figs

    showLog([m], img, META, {}, null);
    expect(lastLoggedValue()).toBe("1.2345 µm");
  });

  it("no override: CSV row still matches the (unconverted) on-canvas label", () => {
    const img = { w: 1000, h: 1000 };
    const m: Measure = {
      id: "m1",
      kind: "distance",
      pts: [{ x: 0, y: 0 }, { x: 0.85, y: 0 }],
    };
    const label = measureLabel(m, {
      img,
      pixelSize: META.pixel_size,
      pixelUnit: META.pixel_unit,
      tilt: null,
      roiStats: {},
    });
    expect(label).toBe("850 nm");

    showLog([m], img, META, {}, null);
    expect(lastLoggedValue()).toBe(label);
  });

  it("reciprocal calibration ('1/nm'): CSV row still matches the unconverted label", () => {
    const img = { w: 1000, h: 1000 };
    const meta = { pixel_size: 1, pixel_unit: "1/nm" };
    const m: Measure = {
      id: "m1",
      kind: "distance",
      pts: [{ x: 0, y: 0 }, { x: 0.85, y: 0 }],
      displayUnit: "auto",
    };
    const label = measureLabel(m, {
      img,
      pixelSize: meta.pixel_size,
      pixelUnit: meta.pixel_unit,
      tilt: null,
      roiStats: {},
    });
    expect(label).toBe("850 1/nm"); // never "converted" — same raw value, unit verbatim

    showLog([m], img, meta, {}, null);
    expect(lastLoggedValue()).toBe(label);
  });
});

describe("showLog — holed polygon uses NET area, matching the stage (PR #159 review fix 3)", () => {
  // Same 100x100/50x50-hole setup as MeasurePanel.displayUnit.test.tsx's
  // holes describe block (net 7500 nm², the review's own numbers) — this
  // is the third leg of the "stage / panel / CSV must agree" triangle.
  // showLog used to call plain (gross-only) polygonStats, so this would
  // have logged 10000, not 7500.
  const OUTER: Measure["pts"] = [
    { x: 0, y: 0 },
    { x: 1, y: 0 },
    { x: 1, y: 1 },
    { x: 0, y: 1 },
  ];
  const HOLE: { x: number; y: number }[] = [
    { x: 0.25, y: 0.25 },
    { x: 0.75, y: 0.25 },
    { x: 0.75, y: 0.75 },
    { x: 0.25, y: 0.75 },
  ];
  const img = { w: 100, h: 100 };
  const meta = { pixel_size: 1, pixel_unit: "nm" };

  it("without a unit override: CSV net matches the stage", () => {
    const m: Measure = { id: "m1", kind: "polygon", pts: OUTER, holes: [HOLE] };
    const label = measureLabel(m, { img, pixelSize: 1, pixelUnit: "nm", tilt: null, roiStats: {} });
    expect(label).toBe("7500 nm² (1 hole)");

    showLog([m], img, meta, {}, null);
    expect(lastLoggedValue()).toBe("7500 nm²");
  });

  it("with a unit override: CSV net matches the stage's converted value", () => {
    const m: Measure = {
      id: "m1",
      kind: "polygon",
      pts: OUTER,
      holes: [HOLE],
      displayUnit: "um",
    };
    const label = measureLabel(m, {
      img,
      pixelSize: 1,
      pixelUnit: "nm",
      tilt: null,
      roiStats: {},
    });
    expect(label).toBe("0.0075 µm² (1 hole)");

    showLog([m], img, meta, {}, null);
    expect(lastLoggedValue()).toBe("0.0075 µm²");
  });
});
