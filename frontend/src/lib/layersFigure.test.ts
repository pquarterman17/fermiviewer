import { describe, expect, it } from "vitest";

import type { LayersResult } from "./api";
import { layersFigureMeasures } from "./layersFigure";
import type { LayersOverlayState } from "../store/viewerTypes";

const SHAPE = { h: 200, w: 100 };

const overlay = (over: Partial<LayersOverlayState> = {}): LayersOverlayState => ({
  imageId: "img",
  axis: "y",
  interfaces: [50, 120],
  traces: [null, null],
  lateralRange: [0, 100],
  tiltDeg: 0,
  ...over,
});

const result = {
  unit: "nm",
  layers: [
    { index: 0, top: 50, bottom: 120, thickness: 35, thickness_std: null },
  ],
} as unknown as LayersResult;

describe("layersFigureMeasures", () => {
  it("draws one line per interface, in normalised image coordinates", () => {
    const out = layersFigureMeasures(overlay(), result, SHAPE, null);
    const lines = out.filter((m) => m.kind === "line");
    expect(lines).toHaveLength(2);
    // interface at row 50 of a 200-row image is y = 0.25, spanning full width
    expect(lines[0].pts).toEqual([
      { x: 0, y: 0.25 },
      { x: 1, y: 0.25 },
    ]);
  });

  it("labels an interface with the thickness of the layer it tops", () => {
    // the same pairing the results table uses, so a reader moving between
    // the figure and the table never has to re-derive which band a number
    // belongs to
    const out = layersFigureMeasures(overlay(), result, SHAPE, null);
    const lines = out.filter((m) => m.kind === "line");
    expect(lines[0].text).toBe("35 nm");
    // nothing below the last interface to measure
    expect(lines[1].text).toBe("");
  });

  it("exports a tilted stack where it was drawn, not flat", () => {
    // the figure must match the overlay; a flat export of a tilted analysis
    // would put every line somewhere the operator never saw it
    const out = layersFigureMeasures(overlay({ tiltDeg: 10 }), result, SHAPE, null);
    const [a, b] = out.filter((m) => m.kind === "line")[0].pts;
    const riseRows = (b.y - a.y) * SHAPE.h;
    expect(riseRows).toBeCloseTo(-100 * Math.tan(Math.PI / 18), 6);
    // and it pivots about the lateral midpoint, so the centre is unmoved
    expect(((a.y + b.y) / 2) * SHAPE.h).toBeCloseTo(50, 6);
  });

  it("marks the analysed region when one was used", () => {
    const out = layersFigureMeasures(overlay(), result, SHAPE, [11, 21, 60, 80]);
    const box = out.find((m) => m.kind === "box")!;
    // 1-based inclusive rect -> normalised corners
    expect(box.pts[0]).toEqual({ x: 20 / 100, y: 10 / 200 });
    expect(box.pts[1]).toEqual({ x: 80 / 100, y: 60 / 200 });
    expect(box.text).toBe("analysed region");
  });

  it("omits the region box for a whole-image analysis", () => {
    const out = layersFigureMeasures(overlay(), result, SHAPE, null);
    expect(out.some((m) => m.kind === "box")).toBe(false);
  });
});
