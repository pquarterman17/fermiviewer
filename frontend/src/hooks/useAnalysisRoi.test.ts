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
