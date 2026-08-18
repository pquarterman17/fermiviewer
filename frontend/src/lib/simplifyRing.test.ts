// simplifyRing.test.ts — pins for the frozen contract in
// plans/LASSO_EDITING_PLAN.md (branch claude/plans-todo-items-wpk8e9).
// Every pin below was mutation-verified: broken against a deliberately
// wrong implementation (RED), then restored (GREEN). The mutation
// tried for each `it` is noted in its own comment.

import { describe, expect, it } from "vitest";

import { simplifyRing } from "./simplifyRing";

type Pt = { x: number; y: number };

function shoelaceArea(pts: Pt[]): number {
  let sum = 0;
  for (let i = 0; i < pts.length; i++) {
    const a = pts[i];
    const b = pts[(i + 1) % pts.length];
    sum += a.x * b.y - b.x * a.y;
  }
  return Math.abs(sum) / 2;
}

/** A ring densely sampled every 1px along a `side`-length square's
 *  perimeter, starting at the bottom-left corner and going
 *  counter-clockwise (in image y-down coordinates: right, up, left,
 *  down — i.e. a consistent single winding direction, never doubling
 *  back). */
function denseSquare(side: number): Pt[] {
  const pts: Pt[] = [];
  for (let x = 0; x < side; x++) pts.push({ x, y: 0 });
  for (let y = 0; y < side; y++) pts.push({ x: side, y });
  for (let x = side; x > 0; x--) pts.push({ x, y: side });
  for (let y = side; y > 0; y--) pts.push({ x: 0, y });
  return pts;
}

/** Dense circle, r about `r`, `n` points, evenly spaced by angle. */
function denseCircle(r: number, n: number, cx = 0, cy = 0): Pt[] {
  const pts: Pt[] = [];
  for (let k = 0; k < n; k++) {
    const theta = (2 * Math.PI * k) / n;
    pts.push({ x: cx + r * Math.cos(theta), y: cy + r * Math.sin(theta) });
  }
  return pts;
}

/** Asymmetric "egg" ring: radius varies with sin(theta) (odd function,
 *  no mirror symmetry about either axis) plus a tiny index-tied jitter,
 *  so the mutually-farthest pair is a single, tie-free point pair —
 *  needed so rotating the array can't relocate the RDP anchors to a
 *  geometrically different pair. */
function asymmetricEgg(n: number): Pt[] {
  const pts: Pt[] = [];
  for (let k = 0; k < n; k++) {
    const theta = (2 * Math.PI * k) / n;
    const r = 100 + 40 * Math.sin(theta) + 0.01 * Math.sin(k * 7.3);
    pts.push({ x: r * Math.cos(theta), y: r * Math.sin(theta) });
  }
  return pts;
}

function approxContains(pts: Pt[], target: Pt, tol: number): boolean {
  return pts.some(
    (p) => Math.hypot(p.x - target.x, p.y - target.y) <= tol,
  );
}

/** Rotation-independent shape key: the coordinate set as a sorted list
 *  of "x,y" strings (values are exact copies of original sample
 *  points — no interpolation happens in simplifyRing — so string
 *  comparison is safe, not a float-tolerance shortcut). */
function shapeKey(pts: Pt[]): string[] {
  return pts.map((p) => `${p.x},${p.y}`).sort();
}

describe("simplifyRing", () => {
  it("collapses a densely-sampled square to ~its corners (collinear removal)", () => {
    // Mutation tried: replace `if (maxDist <= epsilon)` in rdp() with
    // `if (false)`, so no chain ever collapses -> every one of the
    // square's 400 sampled points survives, RED (400 > 8). Restoring
    // the real epsilon check fixes it, GREEN.
    const ring = denseSquare(100);
    const out = simplifyRing(ring, 1);
    expect(out.length).toBeLessThanOrEqual(8);
    for (const corner of [
      { x: 0, y: 0 },
      { x: 100, y: 0 },
      { x: 100, y: 100 },
      { x: 0, y: 100 },
    ]) {
      expect(approxContains(out, corner, 1)).toBe(true);
    }
  });

  it("keeps a deliberate spike whose deviation is >> epsilon (Convention 2)", () => {
    // Mutation tried: in rdp()'s split, change
    // `rdp(chain.slice(maxIdx), epsilon)` to
    // `rdp(chain.slice(maxIdx + 1), epsilon)` -- an off-by-one that
    // drops the max-deviation split point from BOTH sides (left's
    // `.slice(0, -1)` already drops it, so excluding it from `right`
    // too means it never resurfaces) -> at the first split of the
    // spike's half, that point IS the spike, so it vanishes from the
    // output entirely, RED. Restoring the shared boundary
    // (`chain.slice(maxIdx)`, letting `right` keep it) fixes it,
    // GREEN.
    //
    // Cigar-shaped ellipse (a=150, b=20) so the true mutually-farthest
    // pair is the major-axis ends (dist 300) -- well clear of the
    // spike (dist to either end ~= 161), meaning the spike is NOT
    // chosen as an anchor and its survival genuinely exercises RDP's
    // deviation check, not just "anchors always survive".
    const n = 200;
    const a = 150;
    const b = 20;
    const ring: Pt[] = [];
    for (let k = 0; k < n; k++) {
      const t = (2 * Math.PI * k) / n;
      ring.push({ x: a * Math.cos(t), y: b * Math.sin(t) });
    }
    // Push the point nearest theta=90deg (on the flat/minor-axis side,
    // away from both anchors) out to a spike far beyond epsilon.
    const spikeIdx = Math.round((n * Math.PI) / 2 / (2 * Math.PI));
    const spikeTip = { x: 0, y: 60 };
    ring[spikeIdx] = spikeTip;

    const out = simplifyRing(ring, 5);
    expect(approxContains(out, spikeTip, 1e-9)).toBe(true);
  });

  it(">=3 vertex guarantee: aggressive epsilon returns the ORIGINAL ring unchanged", () => {
    // Mutation tried: remove the `result.length >= 3 ? result : pts`
    // fallback (always return `result`) -> a 2-point degenerate ring
    // comes back instead of the original 4-point ring, RED. Restoring
    // the fallback fixes it, GREEN.
    const thinDiamond: Pt[] = [
      { x: 0, y: 0 },
      { x: 50, y: 1 },
      { x: 100, y: 0 },
      { x: 50, y: -1 },
    ];
    const out = simplifyRing(thinDiamond, 10);
    expect(out).toBe(thinDiamond); // same reference, not a re-collapsed copy
    expect(out).toEqual(thinDiamond);
    expect(out.length).toBe(4);
  });

  it("epsilon <= 0 passes the input through unchanged (same reference)", () => {
    // Mutation tried: change the guard from `epsilon <= 0` to
    // `epsilon < 0` -> epsilon === 0 falls through to real
    // simplification instead of passthrough, RED. Restoring `<= 0`
    // fixes it, GREEN.
    // Same reference (not merely deep-equal): simplifyRing does no
    // work at all when epsilon <= 0, so there is nothing to allocate
    // and no reason to copy — this mirrors the epsilon<=0 "no-op"
    // reading of the contract as literally as possible.
    const ring = denseSquare(20);
    expect(simplifyRing(ring, 0)).toBe(ring);
    expect(simplifyRing(ring, -5)).toBe(ring);
  });

  it("dense circle at eps=2: area drift bounded, vertex count drops well below 60", () => {
    // Bound: |ΔA|/A <= 3% and output vertex count < 60. The classic
    // circle-sagitta estimate for RDP on a radius-R circle at
    // tolerance eps predicts a per-chord area loss of about
    // (2/3)*eps*chord where chord ~= 2*sqrt(2*R*eps): for R=100,
    // eps=2 that works out to ~2.5-3% relative drift and ~16
    // vertices, matching what's measured here (~2.55%, ~16 vertices)
    // — comfortably inside this 3% bound and the plan's "~2%" order
    // of magnitude, and far below the 60-vertex ceiling.
    const ring = denseCircle(100, 600);
    const originalArea = shoelaceArea(ring);
    const out = simplifyRing(ring, 2);
    const simplifiedArea = shoelaceArea(out);
    const relDrift = Math.abs(simplifiedArea - originalArea) / originalArea;

    expect(out.length).toBeLessThan(60);
    expect(relDrift).toBeLessThan(0.03);
  });

  it("subsequence property: every output point is one of the input's own points, in order", () => {
    // Mutation tried: in rdp()'s split, return
    // `right.concat(left.slice(0, -1))` (swap concat order) -> output
    // points still all come from the input set, but out of order, so
    // the "unwrapped indices strictly increasing" check fails, RED.
    // Restoring `left.slice(0, -1).concat(right)` fixes it, GREEN.
    const ring = asymmetricEgg(150);
    const out = simplifyRing(ring, 3);

    const indices = out.map((p) => ring.indexOf(p));
    expect(indices.every((idx) => idx !== -1)).toBe(true); // every point IS an input point (by reference)

    const base = indices[0];
    const n = ring.length;
    const unwrapped = indices.map((idx) => (idx - base + n) % n);
    for (let k = 1; k < unwrapped.length; k++) {
      expect(unwrapped[k]).toBeGreaterThan(unwrapped[k - 1]);
    }
  });

  it("closed-ring seam: rotating the input by k leaves the simplified SHAPE unchanged", () => {
    // Mutation tried: replace the closed-ring two-anchor split with a
    // naive open-polyline RDP pinned at index 0 (i.e.
    // `rdp(pts.concat([pts[0]]), epsilon)` with the appended point
    // dropped again, treating index 0 as a fixed start/end anchor) ->
    // rotating the input changes which point is "index 0", so the
    // simplified vertex set differs across rotations (verified: the
    // shapeKey arrays actually differ point-for-point after a k=1
    // rotation), RED. Restoring the farthest-pair anchoring (a
    // rotation-invariant property of the point set) fixes it, GREEN.
    const ring = asymmetricEgg(120);
    const epsilon = 3;
    const base = simplifyRing(ring, epsilon);
    const baseKey = shapeKey(base);

    for (const k of [1, 30, 59, 90, 119]) {
      const rotated = ring.slice(k).concat(ring.slice(0, k));
      const out = simplifyRing(rotated, epsilon);
      expect(shapeKey(out)).toEqual(baseKey);
    }
  });
});
