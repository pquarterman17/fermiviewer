// Freehand (lasso) point accumulation + the polygon "close on first
// vertex" test — split out of useStagePointers.ts (plan item 14) to keep
// that hook under the frontend size ratchet. Pure, no React/Zustand:
// Stage's pointer handlers own the ref that carries a LassoCapture across
// pointermove events; closed-shape RENDERING lives in closedShapeGlyph.tsx
// instead, so this module is capture-geometry only.

export interface LassoCapture {
  pts: { x: number; y: number }[];
}

/** Hard ceiling on a single capture's point count (item 17). The
 *  distance-based decimation in appendLassoPoint already keeps ordinary
 *  drags small, but it is a per-step filter: a sufficiently long or slow
 *  drag (or a user-set tolerance near zero) can still accumulate points
 *  without bound. This is the backstop — once hit, further points are
 *  dropped outright rather than growing the Measure further. 2000 points
 *  is generous for any real outline while keeping polygonStats and the
 *  overlay render cheap. */
export const MAX_LASSO_POINTS = 2000;

/** Fixed capture-time decimation step, in SCREEN px (LASSO_EDITING_PLAN
 *  Convention 4). This is a fidelity floor for the Douglas–Peucker input
 *  at close, NOT user-tunable — `lassoSimplifyPx` no longer drives
 *  capture at all; it drives only the close-time `simplifyRing` epsilon
 *  (see finishLasso's call site in useStagePointers.ts). Callers convert
 *  to image-space the same way as before: `LASSO_CAPTURE_STEP_PX / view.z`. */
export const LASSO_CAPTURE_STEP_PX = 1;

/** Start a freehand capture at an image-space point. */
export function startLasso(pt: { x: number; y: number }): LassoCapture {
  return { pts: [pt] };
}

/** Append a point, dropping anything closer than `minStepPx` (image-space)
 *  to the last KEPT point — a cheap streaming decimation so a slow drag
 *  across a large image doesn't balloon the Measure to thousands of
 *  points before it ever reaches the close-time simplifier. Callers pass
 *  `LASSO_CAPTURE_STEP_PX / view.z` so the floor feels the same at any
 *  zoom. Once MAX_LASSO_POINTS is reached, every further point is dropped
 *  regardless of spacing (the hard cap above). */
export function appendLassoPoint(
  cap: LassoCapture,
  pt: { x: number; y: number },
  minStepPx: number,
): LassoCapture {
  if (cap.pts.length >= MAX_LASSO_POINTS) return cap;
  const last = cap.pts[cap.pts.length - 1];
  if (Math.hypot(pt.x - last.x, pt.y - last.y) < minStepPx) return cap;
  return { pts: [...cap.pts, pt] };
}

/** Points ready for finalizeMeasure, or null to drop a too-short drag
 *  (mirrors the marquee tools' w/h >= 2 guard) — a lasso needs at least
 *  3 points to enclose any area. Deliberately does NOT run simplifyRing:
 *  that needs view.z (screen→image epsilon conversion) and the user's
 *  lassoSimplifyPx pref, neither of which this pure module touches — the
 *  call site (useStagePointers.ts, where both are already in scope) runs
 *  `simplifyRing(pts, prefs.lassoSimplifyPx / view.z)` on this function's
 *  result before it reaches finalizeMeasure, keeping this module a pure,
 *  zoom/pref-agnostic capture-geometry gate. */
export function finishLasso(
  cap: LassoCapture,
): { x: number; y: number }[] | null {
  return cap.pts.length >= 3 ? cap.pts : null;
}

/** True if `pt` is within `tolPx` (image-space) of the first of `verts` —
 *  polygon capture closes the shape on a click back near its start,
 *  mirroring the double-click finish gesture. Requires >= 3 committed
 *  vertices so a real polygon exists before it can close. */
export function nearFirstVertex(
  verts: { x: number; y: number }[],
  pt: { x: number; y: number },
  tolPx: number,
): boolean {
  if (verts.length < 3) return false;
  const first = verts[0];
  return Math.hypot(pt.x - first.x, pt.y - first.y) <= tolPx;
}
