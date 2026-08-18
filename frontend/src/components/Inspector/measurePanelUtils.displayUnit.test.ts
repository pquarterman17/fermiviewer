// measure display-units feature — showLog's per-row CSV value must never
// disagree with the stage label for the same measure (mandatory pin:
// "Panel/CSV consistency"). This cross-checks the two INDEPENDENT
// implementations (measureGlyphs.measureLabel vs. showLog's inline
// per-row builder) against each other rather than duplicating one
// expected string, so a copy/paste slip in either one would be caught.

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

  it("37990 nm² polygon area + Auto: CSV row matches the on-canvas label ('0.038 µm²')", () => {
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
    expect(lastLoggedValue()).toBe(label);
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
