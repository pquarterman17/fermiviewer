// The gesture rules that used to be buried in useStagePointers.ts's pointer
// closures (MAIN_PLAN item 1). These are the parts a pointer-event test
// cannot reach without a real drag: which click commits, which finishes,
// where the live-cursor point goes, and the off-by-one edges of the 1-based
// pixel / crop conversions.

import { describe, expect, it } from "vitest";

import type { Measure } from "../../store/viewerTypes";
import {
  clickCaptureAction,
  cropRectFromPoints,
  findHoleHost,
  fixedZoomCorners,
  imagePointToPixel,
  measuresInRect,
  pendingAfterMove,
  pointInPolygon,
  polyFinishAction,
  polygonContainsRing,
  scanPositionFromPixel,
  spansMinRegion,
} from "./pointerDecisions";

const IMG = { w: 100, h: 50 };

describe("clickCaptureAction", () => {
  it("first click of a 2-click measure starts a pending capture whose last point is the live cursor", () => {
    const act = clickCaptureAction("distance", null, { x: 10, y: 20 }, false, 1);
    expect(act).toEqual({
      kind: "pending",
      pending: {
        kind: "distance",
        pts: [
          { x: 10, y: 20 },
          { x: 10, y: 20 },
        ],
      },
    });
  });

  it("the final click REPLACES the live cursor point instead of appending it", () => {
    const pending = {
      kind: "distance" as const,
      pts: [
        { x: 0, y: 0 },
        { x: 5, y: 5 }, // live cursor, must not survive
      ],
    };
    const act = clickCaptureAction("distance", pending, { x: 10, y: 20 }, false, 1);
    expect(act).toEqual({
      kind: "measure",
      measure: "distance",
      pts: [
        { x: 0, y: 0 },
        { x: 10, y: 20 },
      ],
    });
  });

  it("respects each mode's click count (angle needs three)", () => {
    const pending = {
      kind: "angle" as const,
      pts: [
        { x: 0, y: 0 },
        { x: 1, y: 1 },
        { x: 2, y: 2 }, // live cursor
      ],
    };
    const act = clickCaptureAction("angle", pending, { x: 3, y: 3 }, false, 1);
    expect(act).toEqual({
      kind: "measure",
      measure: "angle",
      pts: [
        { x: 0, y: 0 },
        { x: 1, y: 1 },
        { x: 3, y: 3 },
      ],
    });
  });

  it("previews a calibration line as a plain distance measure, then finalizes as a calibration", () => {
    const first = clickCaptureAction("calibrate", null, { x: 0, y: 0 }, false, 1);
    // the preview kind is what the overlay draws — NOT "calibrate"
    expect(first).toMatchObject({ kind: "pending", pending: { kind: "distance" } });
    const pending = {
      kind: "distance" as const,
      pts: [
        { x: 0, y: 0 },
        { x: 9, y: 9 },
      ],
    };
    const act = clickCaptureAction("calibrate", pending, { x: 50, y: 3 }, false, 1);
    expect(act).toEqual({
      kind: "calibration",
      // H/V snap: the drag favours x, so y collapses onto the first point
      pts: [
        { x: 0, y: 0 },
        { x: 50, y: 0 },
      ],
    });
  });

  it("Shift frees the calibration snap", () => {
    const pending = {
      kind: "distance" as const,
      pts: [
        { x: 0, y: 0 },
        { x: 9, y: 9 },
      ],
    };
    const act = clickCaptureAction("calibrate", pending, { x: 50, y: 3 }, true, 1);
    expect(act).toEqual({
      kind: "calibration",
      pts: [
        { x: 0, y: 0 },
        { x: 50, y: 3 },
      ],
    });
  });

  it("closes a polygon on a click back near its first vertex, dropping the live cursor point", () => {
    const pending = {
      kind: "polygon" as const,
      pts: [
        { x: 0, y: 0 },
        { x: 10, y: 0 },
        { x: 5, y: 10 },
        { x: 1, y: 1 }, // live cursor
      ],
    };
    const act = clickCaptureAction("polygon", pending, { x: 1, y: 0 }, false, 1);
    expect(act).toEqual({
      kind: "measure",
      measure: "polygon",
      pts: [
        { x: 0, y: 0 },
        { x: 10, y: 0 },
        { x: 5, y: 10 },
      ],
    });
  });

  it("scales the polygon close tolerance by zoom, so the same click accumulates when zoomed in", () => {
    const pending = {
      kind: "polygon" as const,
      pts: [
        { x: 0, y: 0 },
        { x: 10, y: 0 },
        { x: 5, y: 10 },
        { x: 1, y: 1 },
      ],
    };
    // 8 screen px / z=8 → 1 image px tolerance; 1.5 px away is not a close
    const act = clickCaptureAction("polygon", pending, { x: 1.5, y: 0 }, false, 8);
    expect(act.kind).toBe("pending");
    // vertex committed, plus a fresh trailing live-cursor point
    expect(act.kind === "pending" && act.pending.pts).toHaveLength(5);
  });
});

describe("pendingAfterMove", () => {
  it("moves the trailing live point without committing a vertex", () => {
    const pending = {
      kind: "polyline" as const,
      pts: [
        { x: 0, y: 0 },
        { x: 1, y: 1 },
      ],
    };
    expect(pendingAfterMove(pending, "polyline", { x: 9, y: 9 }, false)).toEqual({
      kind: "polyline",
      pts: [
        { x: 0, y: 0 },
        { x: 9, y: 9 },
      ],
    });
  });

  it("H/V-snaps the live point while calibrating unless Shift is held", () => {
    const pending = {
      kind: "distance" as const,
      pts: [
        { x: 0, y: 0 },
        { x: 2, y: 2 },
      ],
    };
    const snapped = pendingAfterMove(pending, "calibrate", { x: 50, y: 3 }, false);
    expect(snapped.pts[1]).toEqual({ x: 50, y: 0 });
    const free = pendingAfterMove(pending, "calibrate", { x: 50, y: 3 }, true);
    expect(free.pts[1]).toEqual({ x: 50, y: 3 });
  });
});

describe("polyFinishAction", () => {
  it("drops the double-click's duplicate vertex AND its live cursor point", () => {
    const act = polyFinishAction({
      kind: "polygon",
      pts: [
        { x: 0, y: 0 },
        { x: 10, y: 0 },
        { x: 5, y: 10 },
        { x: 5, y: 10 }, // duplicate from the second pointerdown
        { x: 5, y: 10 }, // live cursor
      ],
    });
    expect(act).toEqual({
      kind: "measure",
      measure: "polygon",
      pts: [
        { x: 0, y: 0 },
        { x: 10, y: 0 },
        { x: 5, y: 10 },
      ],
    });
  });

  it("cancels a polygon left with fewer than 3 vertices", () => {
    const act = polyFinishAction({
      kind: "polygon",
      pts: [
        { x: 0, y: 0 },
        { x: 10, y: 0 },
        { x: 10, y: 0 },
        { x: 10, y: 0 },
      ],
    });
    expect(act).toEqual({ kind: "cancel" });
  });

  it("a polyline only needs 2 vertices, so the same point count finishes", () => {
    const act = polyFinishAction({
      kind: "polyline",
      pts: [
        { x: 0, y: 0 },
        { x: 10, y: 0 },
        { x: 10, y: 0 },
        { x: 10, y: 0 },
      ],
    });
    expect(act).toEqual({
      kind: "measure",
      measure: "polyline",
      pts: [
        { x: 0, y: 0 },
        { x: 10, y: 0 },
      ],
    });
  });
});

describe("imagePointToPixel", () => {
  it("is 1-based: anything in the first pixel is [1, 1]", () => {
    expect(imagePointToPixel({ x: 0, y: 0 }, IMG)).toEqual([1, 1]);
    expect(imagePointToPixel({ x: 0.9, y: 0.9 }, IMG)).toEqual([1, 1]);
  });

  it("returns [row, col] — y first", () => {
    expect(imagePointToPixel({ x: 41.2, y: 7.8 }, IMG)).toEqual([8, 42]);
  });

  it("clamps to the image at both ends (never 0, never past w/h)", () => {
    expect(imagePointToPixel({ x: -5, y: -5 }, IMG)).toEqual([1, 1]);
    expect(imagePointToPixel({ x: 99.9, y: 49.9 }, IMG)).toEqual([50, 100]);
    expect(imagePointToPixel({ x: 500, y: 500 }, IMG)).toEqual([50, 100]);
  });
});

describe("scanPositionFromPixel", () => {
  it("un-offsets imagePointToPixel's 1-basing back to a 0-based {y, x}", () => {
    expect(scanPositionFromPixel([1, 1])).toEqual({ y: 0, x: 0 });
    expect(scanPositionFromPixel([8, 42])).toEqual({ y: 7, x: 41 });
  });

  it("composes with imagePointToPixel to go straight from an image point to a scan position", () => {
    const pixel = imagePointToPixel({ x: 41.2, y: 7.8 }, IMG);
    expect(scanPositionFromPixel(pixel)).toEqual({ y: 7, x: 41 });
  });

  it("row maps to y and col maps to x — never swapped", () => {
    // a broken axis order would make this pass one way and fail transposed
    expect(scanPositionFromPixel([3, 9])).toEqual({ y: 2, x: 8 });
    expect(scanPositionFromPixel([3, 9])).not.toEqual({ y: 8, x: 2 });
  });
});

describe("fixedZoomCorners", () => {
  it("centres an exactly W×H box on the click", () => {
    const [a, b] = fixedZoomCorners({ x: 50, y: 60 }, 20, 10);
    expect(a).toEqual({ x: 40, y: 55 });
    expect(b).toEqual({ x: 60, y: 65 });
    expect(b.x - a.x).toBe(20);
    expect(b.y - a.y).toBe(10);
  });
});

describe("spansMinRegion", () => {
  it("needs 2 image px in BOTH axes, in either drag direction", () => {
    expect(spansMinRegion({ x: 0, y: 0 }, { x: 2, y: 2 })).toBe(true);
    expect(spansMinRegion({ x: 2, y: 2 }, { x: 0, y: 0 })).toBe(true);
    expect(spansMinRegion({ x: 0, y: 0 }, { x: 1.9, y: 9 })).toBe(false);
    expect(spansMinRegion({ x: 0, y: 0 }, { x: 9, y: 1.9 })).toBe(false);
  });
});

describe("cropRectFromPoints", () => {
  it("converts to a 1-based inclusive window, corner order independent", () => {
    const rect = cropRectFromPoints(
      { x: 10.2, y: 20.4 },
      { x: 30.6, y: 40.8 },
      IMG,
    );
    expect(rect).toEqual({ row0: 21, col0: 11, row1: 41, col1: 31 });
    expect(
      cropRectFromPoints({ x: 30.6, y: 40.8 }, { x: 10.2, y: 20.4 }, IMG),
    ).toEqual(rect);
  });

  it("never indexes outside the image (a full-image drag stays 1..w / 1..h)", () => {
    expect(cropRectFromPoints({ x: 0, y: 0 }, { x: 100, y: 50 }, IMG)).toEqual({
      row0: 1,
      col0: 1,
      row1: 50,
      col1: 100,
    });
  });

  it("rejects a drag too small to be a region", () => {
    expect(cropRectFromPoints({ x: 5, y: 5 }, { x: 6, y: 6 }, IMG)).toBeNull();
  });
});

describe("measuresInRect", () => {
  const m = (id: string, pts: { x: number; y: number }[]): Measure => ({
    id,
    kind: "distance",
    pts,
  });
  // normalized 0-1 coords; the rect below is image-space (0,0)-(50,50)
  const measures = [
    m("in", [{ x: 0.1, y: 0.1 }]),
    m("out", [{ x: 0.9, y: 0.9 }]),
    m("partial", [
      { x: 0.9, y: 0.9 },
      { x: 0.2, y: 0.2 },
    ]),
  ];

  it("selects a measure when ANY of its points is inside, preserving order", () => {
    const hits = measuresInRect(measures, { x: 0, y: 0 }, { x: 50, y: 50 }, IMG);
    expect(hits).toEqual(["in", "partial"]);
  });

  it("does not care which corner the drag started from", () => {
    expect(
      measuresInRect(measures, { x: 50, y: 50 }, { x: 0, y: 0 }, IMG),
    ).toEqual(["in", "partial"]);
  });

  it("returns nothing for an empty measure list", () => {
    expect(measuresInRect([], { x: 0, y: 0 }, { x: 99, y: 49 }, IMG)).toEqual([]);
  });
});

const SQUARE10: { x: number; y: number }[] = [
  { x: 0, y: 0 },
  { x: 10, y: 0 },
  { x: 10, y: 10 },
  { x: 0, y: 10 },
];

// A "U"-shaped concave polygon: a 10x10 square with a notch cut from the
// top, from x=4..6 down to y=4. (5, 8) sits inside the notch — inside the
// polygon's bounding box, but outside the actual outline — so it is the
// case a bounding-box shortcut gets wrong and a real point-in-polygon test
// gets right.
const U_SHAPE: { x: number; y: number }[] = [
  { x: 0, y: 0 },
  { x: 10, y: 0 },
  { x: 10, y: 10 },
  { x: 6, y: 10 },
  { x: 6, y: 4 },
  { x: 4, y: 4 },
  { x: 4, y: 10 },
  { x: 0, y: 10 },
];

describe("pointInPolygon", () => {
  it("is true for a point well inside a square", () => {
    expect(pointInPolygon({ x: 5, y: 5 }, SQUARE10)).toBe(true);
  });

  it("is false for a point well outside a square", () => {
    expect(pointInPolygon({ x: 15, y: 5 }, SQUARE10)).toBe(false);
  });

  it("is false inside the notch of a concave polygon, even though the notch is inside the bounding box", () => {
    expect(pointInPolygon({ x: 5, y: 8 }, U_SHAPE)).toBe(false);
  });

  it("is true inside one of the concave polygon's solid legs", () => {
    expect(pointInPolygon({ x: 2, y: 8 }, U_SHAPE)).toBe(true);
    expect(pointInPolygon({ x: 8, y: 8 }, U_SHAPE)).toBe(true);
  });
});

describe("polygonContainsRing", () => {
  it("is true when every ring vertex is inside the host", () => {
    const ring = [
      { x: 3, y: 3 },
      { x: 7, y: 3 },
      { x: 7, y: 7 },
      { x: 3, y: 7 },
    ];
    expect(polygonContainsRing(SQUARE10, ring)).toBe(true);
  });

  it("is false when any ring vertex pokes outside the host", () => {
    const ring = [
      { x: 3, y: 3 },
      { x: 12, y: 3 }, // outside
      { x: 7, y: 7 },
    ];
    expect(polygonContainsRing(SQUARE10, ring)).toBe(false);
  });

  it("rejects a ring sitting in a concave host's notch (bounding-box would wrongly accept it)", () => {
    const ringInNotch = [
      { x: 4.5, y: 6 },
      { x: 5.5, y: 6 },
      { x: 5, y: 9 },
    ];
    expect(polygonContainsRing(U_SHAPE, ringInNotch)).toBe(false);
  });
});

describe("findHoleHost", () => {
  const ring = [
    { x: 4, y: 4 },
    { x: 6, y: 4 },
    { x: 6, y: 6 },
    { x: 4, y: 6 },
  ];
  const host: Measure = { id: "host", kind: "polygon", pts: SQUARE10 };

  it("returns null when no region contains the ring", () => {
    expect(findHoleHost([], "ring", ring)).toBeNull();
    const farAway: Measure = {
      id: "far",
      kind: "polygon",
      pts: [
        { x: 100, y: 100 },
        { x: 110, y: 100 },
        { x: 110, y: 110 },
      ],
    };
    expect(findHoleHost([farAway], "ring", ring)).toBeNull();
  });

  it("returns the containing region's id", () => {
    expect(findHoleHost([host], "ring", ring)).toBe("host");
  });

  it("excludes the ring's own id from candidacy (a ring can't be its own host)", () => {
    const selfHost: Measure = { id: "ring", kind: "polygon", pts: SQUARE10 };
    expect(findHoleHost([selfHost], "ring", ring)).toBeNull();
  });

  it("ignores candidates that aren't polygon/lasso, even if they geometrically contain the ring", () => {
    const roiHost: Measure = { id: "roi1", kind: "roi", pts: SQUARE10 };
    expect(findHoleHost([roiHost], "ring", ring)).toBeNull();
  });

  it("picks the SMALLEST containing region when two overlap (deterministic, not array order)", () => {
    const outer: Measure = { id: "outer", kind: "polygon", pts: SQUARE10 };
    const inner: Measure = {
      id: "inner",
      kind: "lasso",
      pts: [
        { x: 2, y: 2 },
        { x: 8, y: 2 },
        { x: 8, y: 8 },
        { x: 2, y: 8 },
      ],
    };
    // order shouldn't matter — try both
    expect(findHoleHost([outer, inner], "ring", ring)).toBe("inner");
    expect(findHoleHost([inner, outer], "ring", ring)).toBe("inner");
  });
});
