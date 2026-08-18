// simplifyRing.ts — Douglas–Peucker simplification for a CLOSED ring.
// Pure geometry: imports nothing from components/. See
// plans/LASSO_EDITING_PLAN.md "Frozen contract" (on branch
// claude/plans-todo-items-wpk8e9) for the governing spec. The
// degenerate fallback mirrors the spirit of
// calc/contours.py::_simplify, which falls back to the un-simplified
// ring rather than return an unusable (<3-vertex) degenerate shape.

type Pt = { x: number; y: number };

/** Douglas–Peucker for a CLOSED ring. epsilon in IMAGE px (caller
 *  converts from screen px). Anchors: the two mutually-farthest ring
 *  points (found from the extremes), each half simplified
 *  independently, halves rejoined. Result always has >= 3 vertices;
 *  if simplification would collapse below 3, the ORIGINAL ring is
 *  returned unchanged (mirrors calc/contours.py::_simplify's
 *  degenerate fallback). epsilon <= 0 returns the input unchanged. */
export function simplifyRing(
  pts: { x: number; y: number }[],
  epsilon: number,
): { x: number; y: number }[] {
  if (epsilon <= 0) return pts;
  if (pts.length < 3) return pts;

  const [i, j] = farthestPair(pts);

  // Two forward arcs, never reversed, so the output stays a
  // subsequence of `pts` in its original cyclic order: i -> j, then
  // j -> i (wrapping past the end). Together they retrace the whole
  // ring exactly once.
  const half1 = arcForward(pts, i, j);
  const half2 = arcForward(pts, j, i);

  const s1 = rdp(half1, epsilon);
  const s2 = rdp(half2, epsilon);

  // s1 = [pts[i], ..., pts[j]], s2 = [pts[j], ..., pts[i]] — both
  // anchors already appear as s1's ends, so drop s2's shared first
  // and last entries to avoid double-counting the seam.
  const result = s1.concat(s2.slice(1, -1));

  return result.length >= 3 ? result : pts;
}

/** Exact O(n^2) mutually-farthest pair (the true ring "diameter").
 *  Affordable at the lasso's hard cap of 2000 points and comfortably
 *  beyond it — per the frozen contract this is deliberately simpler
 *  than rotating calipers over a convex hull "found from the
 *  extremes" while being exact (not an approximation) for n up to
 *  ~4000, which is the documented bound for this brute force. */
function farthestPair(pts: Pt[]): [number, number] {
  let bestI = 0;
  let bestJ = 1;
  let bestD = -1;
  for (let a = 0; a < pts.length; a++) {
    for (let b = a + 1; b < pts.length; b++) {
      const d = dist2(pts[a], pts[b]);
      if (d > bestD) {
        bestD = d;
        bestI = a;
        bestJ = b;
      }
    }
  }
  return [bestI, bestJ];
}

/** Points from index `from` to index `to`, walking forward and
 *  wrapping past the array end, inclusive of both ends. Never walks
 *  backward, so callers get a genuine subsequence of `pts`. */
function arcForward(pts: Pt[], from: number, to: number): Pt[] {
  const n = pts.length;
  const out: Pt[] = [pts[from]];
  for (let k = (from + 1) % n; ; k = (k + 1) % n) {
    out.push(pts[k]);
    if (k === to) break;
  }
  return out;
}

function dist2(a: Pt, b: Pt): number {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  return dx * dx + dy * dy;
}

/** Perpendicular distance from `p` to the line through `a`-`b`, or the
 *  plain point-to-point distance to `a` when `a` and `b` coincide
 *  (a zero-length segment has no well-defined perpendicular). */
function perpDist(p: Pt, a: Pt, b: Pt): number {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const lenSq = dx * dx + dy * dy;
  if (lenSq === 0) return Math.hypot(p.x - a.x, p.y - a.y);
  const t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / lenSq;
  const projX = a.x + t * dx;
  const projY = a.y + t * dy;
  return Math.hypot(p.x - projX, p.y - projY);
}

/** Standard recursive Douglas–Peucker over an open polyline. `chain`'s
 *  first and last points are anchors: they are always kept, and every
 *  returned point is one of `chain`'s own objects (no interpolation),
 *  which is what keeps `simplifyRing`'s output a true subsequence. */
function rdp(chain: Pt[], epsilon: number): Pt[] {
  if (chain.length <= 2) return chain;
  const first = chain[0];
  const last = chain[chain.length - 1];
  let maxDist = -1;
  let maxIdx = 0;
  for (let k = 1; k < chain.length - 1; k++) {
    const d = perpDist(chain[k], first, last);
    if (d > maxDist) {
      maxDist = d;
      maxIdx = k;
    }
  }
  if (maxDist <= epsilon) return [first, last];
  const left = rdp(chain.slice(0, maxIdx + 1), epsilon);
  const right = rdp(chain.slice(maxIdx), epsilon);
  return left.slice(0, -1).concat(right);
}
