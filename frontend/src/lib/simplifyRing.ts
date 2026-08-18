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
 *  points — exact for n <= 4000, approximated from the 8 coordinate
 *  extremes above that (see farthestPair) — each half simplified
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

/** Mutually-farthest ring-point pair used to anchor the closed-ring RDP
 *  split. Two regimes, chosen by input size:
 *
 *  - n <= 4000: EXACT O(n^2) brute force over every pair (the true ring
 *    "diameter") — per the frozen contract this is deliberately simpler
 *    than rotating calipers over a convex hull while being exact (not an
 *    approximation), and affordable up to ~4000 points, which is the
 *    documented bound for this brute force.
 *  - n > 4000 (the lasso path budget fix raised MAX_LASSO_POINTS in
 *    regionCapture.ts to 8000, past where O(n^2) stays cheap): an O(n)
 *    approximation — the farthest pair AMONG THE 8 COORDINATE EXTREMES
 *    (argmin/argmax of x, y, x+y, x-y). Those 8 candidates are picked by
 *    COORDINATE VALUE, not array index, so — like the exact brute force —
 *    this stays rotation-invariant: rotating a ring's point array
 *    relabels indices but leaves the coordinate set unchanged, so the
 *    same 8 points (and therefore the same chosen pair) come out no
 *    matter where the array starts, which is what the closed-ring seam
 *    property depends on. The chosen pair need not be the TRUE diameter
 *    (an adversarial shape can hide it off all 8 extremes) — RDP's split
 *    only needs two well-separated anchors, not the exact diameter, and
 *    on any real ring the 8 extremes are spread across its bounding
 *    directions, which is enough separation for that. */
function farthestPair(pts: Pt[]): [number, number] {
  return pts.length > 4000
    ? farthestPairFromExtremes(pts)
    : farthestPairExact(pts);
}

/** n <= 4000 regime: exact O(n^2) brute force over every pair. */
function farthestPairExact(pts: Pt[]): [number, number] {
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

/** n > 4000 regime: O(n) single pass to find the 8 coordinate extremes
 *  (argmin/argmax of x, y, x+y, x-y), then the farthest pair among just
 *  those (at most 8-choose-2 = 28 pairs — O(1) relative to n). */
function farthestPairFromExtremes(pts: Pt[]): [number, number] {
  let iMinX = 0,
    iMaxX = 0,
    iMinY = 0,
    iMaxY = 0,
    iMinSum = 0,
    iMaxSum = 0,
    iMinDiff = 0,
    iMaxDiff = 0;
  for (let k = 1; k < pts.length; k++) {
    const p = pts[k];
    if (p.x < pts[iMinX].x) iMinX = k;
    if (p.x > pts[iMaxX].x) iMaxX = k;
    if (p.y < pts[iMinY].y) iMinY = k;
    if (p.y > pts[iMaxY].y) iMaxY = k;
    const sum = p.x + p.y;
    if (sum < pts[iMinSum].x + pts[iMinSum].y) iMinSum = k;
    if (sum > pts[iMaxSum].x + pts[iMaxSum].y) iMaxSum = k;
    const diff = p.x - p.y;
    if (diff < pts[iMinDiff].x - pts[iMinDiff].y) iMinDiff = k;
    if (diff > pts[iMaxDiff].x - pts[iMaxDiff].y) iMaxDiff = k;
  }
  const candidates = [
    iMinX,
    iMaxX,
    iMinY,
    iMaxY,
    iMinSum,
    iMaxSum,
    iMinDiff,
    iMaxDiff,
  ];
  let bestI = candidates[0];
  let bestJ = candidates[1];
  let bestD = -1;
  for (let a = 0; a < candidates.length; a++) {
    for (let b = a + 1; b < candidates.length; b++) {
      const ia = candidates[a];
      const ib = candidates[b];
      const d = dist2(pts[ia], pts[ib]);
      if (d > bestD) {
        bestD = d;
        bestI = ia;
        bestJ = ib;
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
