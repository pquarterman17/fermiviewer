// Pure lasso/polygon capture geometry (plan item 14) — decimation must not
// lose points beyond the min-step threshold, and nearFirstVertex must
// require a real (>= 3 vertex) polygon before "closing" fires.

import { describe, expect, it } from "vitest";

import {
  appendLassoPoint,
  finishLasso,
  nearFirstVertex,
  startLasso,
} from "./regionCapture";

describe("regionCapture", () => {
  it("starts a capture with exactly the seed point", () => {
    const cap = startLasso({ x: 1, y: 2 });
    expect(cap.pts).toEqual([{ x: 1, y: 2 }]);
  });

  it("drops points closer than minStepPx to the last kept point", () => {
    let cap = startLasso({ x: 0, y: 0 });
    cap = appendLassoPoint(cap, { x: 0.5, y: 0 }, 2); // too close — dropped
    expect(cap.pts).toHaveLength(1);
    cap = appendLassoPoint(cap, { x: 3, y: 0 }, 2); // far enough — kept
    expect(cap.pts).toHaveLength(2);
    expect(cap.pts[1]).toEqual({ x: 3, y: 0 });
  });

  it("finishLasso requires >= 3 points to enclose any area", () => {
    let cap = startLasso({ x: 0, y: 0 });
    cap = appendLassoPoint(cap, { x: 10, y: 0 }, 1);
    expect(finishLasso(cap)).toBeNull(); // only 2 points
    cap = appendLassoPoint(cap, { x: 10, y: 10 }, 1);
    expect(finishLasso(cap)).toHaveLength(3);
  });

  it("nearFirstVertex requires a real polygon (>= 3 verts) before closing", () => {
    const verts = [
      { x: 0, y: 0 },
      { x: 10, y: 0 },
    ];
    expect(nearFirstVertex(verts, { x: 0.5, y: 0 }, 5)).toBe(false); // 2 verts
    const triangle = [...verts, { x: 5, y: 10 }];
    expect(nearFirstVertex(triangle, { x: 0.5, y: 0 }, 5)).toBe(true);
    expect(nearFirstVertex(triangle, { x: 50, y: 50 }, 5)).toBe(false);
  });
});
