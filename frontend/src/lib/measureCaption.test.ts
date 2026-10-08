// "Edit caption…" on value measures: stored on Measure.text but used to be
// invisible — the stage label and the Measurements list now lead with it.

import { describe, expect, it } from "vitest";

import { measureRowValue } from "../components/Inspector/measurePanelUtils";
import { measureLabel } from "../components/Stage/measureGlyphs";
import type { Measure } from "../store/viewerTypes";
import { withCaption } from "./measureCaption";

const img = { w: 100, h: 100 };
const ctx = {
  img,
  pixelSize: 1,
  pixelUnit: "nm",
  tilt: null,
  roiStats: { r: { mean: 4, std: 1 } } as never,
};
const meta = { pixel_size: 1, pixel_unit: "nm" };

function mk(kind: Measure["kind"], text?: string): Measure {
  const pts =
    kind === "angle"
      ? [{ x: 0.5, y: 0 }, { x: 0, y: 0 }, { x: 0, y: 0.5 }]
      : [{ x: 0, y: 0 }, { x: 0.5, y: 0 }];
  return { id: "r", kind, pts, text } as Measure;
}

describe("measure captions", () => {
  it("withCaption prefixes only a non-blank caption", () => {
    expect(withCaption({ text: "A" }, "5 nm")).toBe("A · 5 nm");
    expect(withCaption({ text: "  " }, "5 nm")).toBe("5 nm");
    expect(withCaption({}, "5 nm")).toBe("5 nm");
  });

  it.each([
    ["distance", "50 nm"],
    ["profile", "50 nm"],
    ["polyline", "50 nm"],
    ["angle", "90.0°"],
  ] as const)("%s shows caption + value on stage and in the list", (kind, v) => {
    expect(measureLabel(mk(kind, "grain A"), ctx)).toBe(`grain A · ${v}`);
    expect(measureRowValue(mk(kind, "grain A"), img, meta, {}, null)).toBe(
      `grain A · ${v}`,
    );
    expect(measureLabel(mk(kind), ctx)).toBe(v);
  });

  it("ROI/ellipse captions lead the stats; annotation kinds stay caption-only", () => {
    expect(measureLabel(mk("roi", "bg"), ctx)).toBe("bg · μ 4 · σ 1");
    expect(measureLabel(mk("ellipse", "bg"), ctx)).toBe("bg · μ 4 · σ 1");
    expect(measureLabel(mk("box", "note"), ctx)).toBe("note");
    expect(measureRowValue(mk("arrow", "note"), img, meta, {}, null)).toBe("note");
  });
});
