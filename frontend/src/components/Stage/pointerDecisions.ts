// Pure capture DECISIONS for useStagePointers.ts (MAIN_PLAN item 1) —
// "given the capture mode, the point under the cursor and the pending
// capture, what should happen?". The bulk of those pointer handlers was
// decision logic rather than state mutation, so the decisions live here as
// plain functions returning a described action and the hook is left as a
// thin dispatcher that applies one. Same rule as regionCapture.ts, which
// came out of the same file for the same reason: no React, no Zustand, no
// lib/api — values in, values out, so every gesture rule is unit-testable
// without a DOM or a store.

import type { Size } from "../../lib/geometry";
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
