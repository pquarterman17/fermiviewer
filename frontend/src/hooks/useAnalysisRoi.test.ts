import { describe, expect, it } from "vitest";

import {
  layerOverlayCoordinates,
  roiLocalDepths,
  toAnalysisRoi,
} from "./useAnalysisRoi";

describe("analysis ROI coordinates", () => {
  it("converts normalized endpoints to a clamped 1-based inclusive box", () => {
    expect(toAnalysisRoi({
      kind: "roi",
      pts: [{ x: 0.75, y: 0.8 }, { x: 0.25, y: 0.2 }],
    }, [100, 200])).toEqual([21, 51, 80, 150]);
  });

  it("translates ROI-local layer overlays and edits", () => {
    const roi = [21, 51, 80, 150] as const;
    expect(layerOverlayCoordinates("y", [4, 12], [[3, 5], null], [...roi]))
      .toEqual({
        interfaces: [24, 32],
        traces: [[23, 25], null],
        lateralOffset: 50,
        lateralRange: [50, 150],
        depthRange: [20, 80],
      });
    expect(roiLocalDepths("y", [24, 32], [...roi])).toEqual([4, 12]);
  });
});

describe("layerOverlayCoordinates with a tilt", () => {
  // A tilted collapse samples along a rotated axis through the ROI's
  // CENTRE, one pixel apart along that axis, and the box is shortened to
  // fit inside the ROI. So depth index i is NOT row roi[0]-1+i: the
  // profile both shrinks and re-centres, and using the untilted offset
  // drew every interface line tens of pixels off the feature.
  const ROI: [number, number, number, number] = [1, 1, 201, 201];

  it("is unchanged when no tilt was applied", () => {
    const out = layerOverlayCoordinates("y", [50], [null], ROI, null);
    expect(out.interfaces[0]).toBe(50);
  });

  it("centres the tilted profile on the ROI instead of its top edge", () => {
    // 20° over a 201 px ROI leaves about 147 samples; the middle sample
    // must land on the ROI's middle row (100), not on row 73
    const nDepth = 147;
    const out = layerOverlayCoordinates(
      "y", [(nDepth - 1) / 2], [null], ROI, { tiltDeg: 20, nDepth },
    );
    expect(out.interfaces[0]).toBeCloseTo(100, 6);
  });

  it("steps by cos(tilt) per sample, because the axis is rotated", () => {
    const nDepth = 147;
    const out = layerOverlayCoordinates(
      "y", [(nDepth - 1) / 2, (nDepth - 1) / 2 + 10], [null, null], ROI,
      { tiltDeg: 20, nDepth },
    );
    const step = out.interfaces[1] - out.interfaces[0];
    // ten samples along a 20°-rotated axis advance 10·cos(20°) rows
    expect(step).toBeCloseTo(10 * Math.cos((20 * Math.PI) / 180), 6);
  });

  it("maps traces through the same transform as the interfaces", () => {
    const nDepth = 147;
    const mid = (nDepth - 1) / 2;
    const out = layerOverlayCoordinates(
      "y", [mid], [[mid, mid]], ROI, { tiltDeg: 20, nDepth },
    );
    expect(out.traces[0]).toEqual([out.interfaces[0], out.interfaces[0]]);
  });
});
