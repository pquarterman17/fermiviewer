// Pure capture DECISIONS for useStagePointers.ts (MAIN_PLAN item 1) —
// "given the capture mode, the point under the cursor and the pending
// capture, what should happen?". The bulk of those pointer handlers was
// decision logic rather than state mutation, so the decisions live here as
// plain functions returning a described action and the hook is left as a
// thin dispatcher that applies one. Same rule as regionCapture.ts, which
// came out of the same file for the same reason: no React, no Zustand, no
// lib/api — values in, values out, so every gesture rule is unit-testable
// without a DOM or a store.

import { polygonStats, type Size } from "../../lib/geometry";
import type { CaptureMode, Measure } from "../../store/viewerTypes";
import { nearFirstVertex } from "./regionCapture";
import { CLICKS, snapHV, type Pt } from "./stageUtils";

/** An in-progress multi-click capture: the committed vertices plus, while
 *  the pointer moves, a trailing live-cursor point. */
export interface PendingMeasure {
  kind: Measure["kind"];
  pts: Pt[];
}

/** What a click or double-click should DO. The hook maps these onto
 *  finalizeMeasure / finalizeCalibration / setPending / setCaptureMode —
 *  nothing in this module touches state itself. */
export type CaptureAction =
  | { kind: "measure"; measure: Measure["kind"]; pts: Pt[] }
  | { kind: "calibration"; pts: Pt[] }
  | { kind: "pending"; pending: PendingMeasure }
  | { kind: "cancel" };

/** Polygon close tolerance in SCREEN px, divided by view.z at the call
 *  site so the grab radius feels the same at every zoom. */
export const POLY_CLOSE_PX = 8;

/** Marquee tools reject a degenerate drag: both spans must reach this many
 *  image px, so a stray click never registers a zero-area region. */
export const MIN_REGION_PX = 2;

/** True if two corners span a region big enough to keep. */
export function spansMinRegion(a: Pt, b: Pt): boolean {
  return (
    Math.abs(b.x - a.x) >= MIN_REGION_PX && Math.abs(b.y - a.y) >= MIN_REGION_PX
  );
}

/** Image-space point → 1-based [row, col] pixel, clamped to the image
 *  (#10) — the pixel specnav publishes for the spectrum workshops. */
export function imagePointToPixel(ip: Pt, imgSize: Size): [number, number] {
  return [
    Math.min(imgSize.h, Math.max(1, Math.floor(ip.y) + 1)),
    Math.min(imgSize.w, Math.max(1, Math.floor(ip.x) + 1)),
  ];
}

/** The two image-space corners of a fixed W×H zoom box centred on `ip`
 *  (A2: a click places the box and the caller zooms to it). */
export function fixedZoomCorners(ip: Pt, w: number, h: number): [Pt, Pt] {
  const hw = w / 2;
  const hh = h / 2;
  return [
    { x: ip.x - hw, y: ip.y - hh },
    { x: ip.x + hw, y: ip.y + hh },
  ];
}

/** A click while a CLICKS-counted mode is armed: commit the click, then
 *  either finish the measure (enough points, or a polygon clicked back
 *  onto its first vertex) or extend the pending capture with a fresh
 *  live-cursor point. `shiftKey` frees the calibration line's H/V snap;
 *  `zoom` is view.z, for the polygon close tolerance. */
export function clickCaptureAction(
  mode: CaptureMode,
  pending: PendingMeasure | null,
  point: Pt,
  shiftKey: boolean,
  zoom: number,
): CaptureAction {
  const need = CLICKS[mode];
  const cur = pending?.pts ?? [];
  // calibration line snaps H/V (Shift = free) so a flat bar traces cleanly
  const ip =
    mode === "calibrate" && cur.length >= 1
      ? snapHV(cur[0], point, shiftKey)
      : point;
  // polygon closes on a click back near its first vertex — the other
  // finish gesture, alongside double-click (polyFinishAction below)
  const verts = cur.slice(0, -1);
  if (
    mode === "polygon" &&
    pending &&
    nearFirstVertex(verts, ip, POLY_CLOSE_PX / zoom)
  ) {
    return { kind: "measure", measure: "polygon", pts: verts };
  }
  // replace the live cursor point with the committed click
  const committed = pending ? [...verts, ip] : [ip];
  if (committed.length >= need) {
    return mode === "calibrate"
      ? { kind: "calibration", pts: committed }
      : { kind: "measure", measure: mode as Measure["kind"], pts: committed };
  }
  return {
    kind: "pending",
    pending: {
      // preview the calibration line as a plain distance line
      kind: mode === "calibrate" ? "distance" : (mode as Measure["kind"]),
      pts: [...committed, ip],
    },
  };
}

/** The pending capture after a pointermove: the trailing live-cursor point
 *  follows the pointer, H/V-snapped to the first vertex while calibrating. */
export function pendingAfterMove(
  pending: PendingMeasure,
  mode: CaptureMode,
  point: Pt,
  shiftKey: boolean,
): PendingMeasure {
  const ip =
    mode === "calibrate" && pending.pts.length >= 1
      ? snapHV(pending.pts[0], point, shiftKey)
      : point;
  return { kind: pending.kind, pts: [...pending.pts.slice(0, -1), ip] };
}

/** Double-click finishing a polyline/polygon: the double-click's two
 *  pointerdowns already committed a duplicate vertex AND a live cursor
 *  point, so drop both. A polygon then needs 3 vertices and a polyline 2;
 *  anything shorter cancels instead of storing a degenerate measure. */
export function polyFinishAction(pending: PendingMeasure): CaptureAction {
  const committed = pending.pts.slice(0, -2);
  const need = pending.kind === "polygon" ? 3 : 2;
  return committed.length >= need
    ? { kind: "measure", measure: pending.kind, pts: committed }
    : { kind: "cancel" };
}

/** 1-based inclusive crop window for applyFilter("crop") from a marquee's
 *  two (already clamped) image-space corners, or null when the drag is too
 *  small to be a region. Round(v + 0.5) maps a 0-based image coordinate
 *  onto the 1-based pixel the server indexes. */
export function cropRectFromPoints(
  a: Pt,
  b: Pt,
  imgSize: Size,
): { row0: number; col0: number; row1: number; col1: number } | null {
  if (!spansMinRegion(a, b)) return null;
  const px = (v: number, n: number) =>
    Math.min(n, Math.max(1, Math.round(v + 0.5)));
  return {
    row0: px(Math.min(a.y, b.y), imgSize.h),
    col0: px(Math.min(a.x, b.x), imgSize.w),
    row1: px(Math.max(a.y, b.y), imgSize.h),
    col1: px(Math.max(a.x, b.x), imgSize.w),
  };
}

/** Ids of every measure with at least one point inside the marquee —
 *  shift-drag multi-select. `a`/`b` are image-space corners in any order;
 *  Measure.pts are normalized 0–1, hence the imgSize divide. */
export function measuresInRect(
  measures: Measure[],
  a: Pt,
  b: Pt,
  imgSize: Size,
): string[] {
  const x0 = Math.min(a.x, b.x) / imgSize.w;
  const x1 = Math.max(a.x, b.x) / imgSize.w;
  const y0 = Math.min(a.y, b.y) / imgSize.h;
  const y1 = Math.max(a.y, b.y) / imgSize.h;
  return measures
    .filter((m) =>
      m.pts.some((p) => p.x >= x0 && p.x <= x1 && p.y >= y0 && p.y <= y1),
    )
    .map((m) => m.id);
}

// ── DRAW A HOLE (plan item 4) ────────────────────────────────────────
// item 19 shipped the area math (lib/geometry polygonStatsWithHoles) and
// the schema field (Measure.holes), but nothing decided WHICH region a
// newly-drawn ring should subtract from. That decision is containment —
// same "given points, what should happen" shape as the rest of this file
// — so it lives here rather than in the store or the context-menu
// component that triggers it (MeasureCtxMenu.tsx).

/** Point-in-polygon via ray casting (even-odd rule) against a CLOSED
 *  polygon — the implicit closing edge back to vertex 0 matches
 *  lib/geometry's polygonStats convention. A point exactly on an edge
 *  may resolve either way; callers here only rely on vertices safely
 *  inside or outside, never on boundary-exact input. */
export function pointInPolygon(pt: Pt, poly: Pt[]): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const a = poly[i];
    const b = poly[j];
    if (a.y > pt.y === b.y > pt.y) continue;
    const xIntersect = ((b.x - a.x) * (pt.y - a.y)) / (b.y - a.y) + a.x;
    if (pt.x < xIntersect) inside = !inside;
  }
  return inside;
}

/** True when EVERY vertex of `ring` lies inside `host`. Deliberately
 *  vertex-by-vertex against the real outline rather than a bounding-box
 *  check — a bounding-box test would wrongly accept a ring that pokes
 *  outside a concave host as long as it stays inside the host's AABB. */
export function polygonContainsRing(host: Pt[], ring: Pt[]): boolean {
  return (
    host.length >= 3 &&
    ring.length > 0 &&
    ring.every((p) => pointInPolygon(p, host))
  );
}

/** Which existing region a ring (a drawn polygon/lasso measure, by id)
 *  should become a hole of, or null if none contains it — the null case
 *  is not an error, just "nothing to attach to" (the ring stays a plain
 *  top-level measure). Candidates are every OTHER polygon/lasso measure
 *  that fully contains the ring (polygonContainsRing); holes are only
 *  meaningful on those two area-bearing kinds (viewerTypes.ts), so an
 *  roi/ellipse/etc that happens to geometrically contain the ring is not
 *  a candidate. When more than one region contains it (concentric or
 *  overlapping regions), the SMALLEST by area wins — the most specific
 *  container, so nesting picks the inner region deterministically rather
 *  than by array order. Areas are compared directly in the measures'
 *  normalized 0-1 space: every candidate on the same image is scaled by
 *  the same w/h, so relative area ordering is unaffected and no image
 *  Size is needed here. */
export function findHoleHost(
  measures: Measure[],
  ringId: string,
  ring: Pt[],
): string | null {
  let bestId: string | null = null;
  let bestArea = Infinity;
  for (const m of measures) {
    if (m.id === ringId) continue;
    if (m.kind !== "polygon" && m.kind !== "lasso") continue;
    if (!polygonContainsRing(m.pts, ring)) continue;
    const area = polygonStats(m.pts).areaPx2;
    if (area < bestArea) {
      bestArea = area;
      bestId = m.id;
    }
  }
  return bestId;
}
