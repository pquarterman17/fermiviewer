// Pure lasso/polygon capture geometry (plan item 14) — decimation must not
// lose points beyond the min-step threshold, and nearFirstVertex must
// require a real (>= 3 vertex) polygon before "closing" fires.

import { describe, expect, it } from "vitest";

import {
  appendLassoPoint,
  finishLasso,
  MAX_LASSO_POINTS,
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

  it("caps the point count (item 17): a long drag stays bounded even with spacing that would otherwise keep every point", () => {
    let cap = startLasso({ x: 0, y: 0 });
    // minStepPx=0 keeps every point — the per-step decimation alone would
    // never stop this drag, so the hard cap is what has to intervene
    for (let i = 0; i < MAX_LASSO_POINTS + 500; i++) {
      cap = appendLassoPoint(cap, { x: i + 1, y: 0 }, 0);
    }
    expect(cap.pts).toHaveLength(MAX_LASSO_POINTS);
    // further points are silently dropped, not appended
    cap = appendLassoPoint(cap, { x: 99999, y: 0 }, 0);
    expect(cap.pts).toHaveLength(MAX_LASSO_POINTS);
    expect(cap.pts.at(-1)).not.toEqual({ x: 99999, y: 0 });
  });

  it("accepts points well beyond the OLD 2000 cap, up to the raised budget (lasso path budget fix)", () => {
    // Mutation-verified against the PRE-fix source (MAX_LASSO_POINTS = 2000):
    // this test fails RED there because appendLassoPoint stops accepting new
    // points once cap.pts.length hits 2000, so a trace of 2500 steps tops
    // out at 2000 kept points, not 2501. Raising MAX_LASSO_POINTS fixes it,
    // GREEN — a long lasso trace no longer gets truncated mid-drag.
    let cap = startLasso({ x: 0, y: 0 });
    for (let i = 0; i < 2500; i++) {
      cap = appendLassoPoint(cap, { x: i + 1, y: 0 }, 0);
    }
    expect(cap.pts.length).toBe(2501); // seed + 2500 accepted moves
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
