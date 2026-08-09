// View-transform math shared by Stage, overlays and (later) measurements.
// Convention (store/viewer.ts): z = screen px per image px,
// (px, py) = normalized image point under the viewport centre.

import type { View } from "../store/viewer";

export interface Size {
  w: number;
  h: number;
}

/** z that letterboxes the whole image into the viewport. */
export function fitZoom(img: Size, vp: Size): number {
  if (img.w === 0 || img.h === 0) return 1;
  return Math.min(vp.w / img.w, vp.h / img.h);
}

export function fitView(img: Size, vp: Size): View {
  return { z: fitZoom(img, vp), px: 0.5, py: 0.5 };
}

/** image pixel → viewport CSS px */
export function imageToScreen(
  ix: number,
  iy: number,
  view: View,
  img: Size,
  vp: Size,
): { x: number; y: number } {
  return {
    x: (ix - view.px * img.w) * view.z + vp.w / 2,
    y: (iy - view.py * img.h) * view.z + vp.h / 2,
  };
}

/** viewport CSS px → image pixel */
export function screenToImage(
  sx: number,
  sy: number,
  view: View,
  img: Size,
  vp: Size,
): { x: number; y: number } {
  return {
    x: (sx - vp.w / 2) / view.z + view.px * img.w,
    y: (sy - vp.h / 2) / view.z + view.py * img.h,
  };
}

/** Zoom about a viewport point so the image pixel under the cursor stays put. */
export function zoomAbout(
  view: View,
  factor: number,
  sx: number,
  sy: number,
  img: Size,
  vp: Size,
): View {
  const z = clampZoom(view.z * factor);
  const p = screenToImage(sx, sy, view, img, vp);
  // solve for the new centre keeping p under (sx, sy)
  return {
    z,
    px: (p.x - (sx - vp.w / 2) / z) / img.w,
    py: (p.y - (sy - vp.h / 2) / z) / img.h,
  };
}

export function clampZoom(z: number): number {
  return Math.min(64, Math.max(1 / 64, z));
}

/** Physical scale of a view: PIXEL_UNIT PER SCREEN PX (not necessarily
 *  µm/nm — `pixelSize` is in the image's own `pixel_unit`; callers label
 *  the result with that unit string, this function never assumes one).
 *  z = screen px per image px, pixelSize = pixel_unit per image px, so
 *  pixelSize / z = pixel_unit per screen px. */
export function physicalScale(view: View, pixelSize: number): number {
  return pixelSize / view.z;
}

/** View hitting a target physical scale (same unit convention as
 *  physicalScale) while keeping a given normalized centre fixed — so
 *  switching to a differently-calibrated image changes zoom, not pan.
 *  z is clamped to the same [1/64, 64] range as interactive zoom. */
export function viewForPhysicalScale(
  targetScale: number,
  pixelSize: number,
  centre: { px: number; py: number },
): View {
  return {
    z: clampZoom(pixelSize / targetScale),
    px: centre.px,
    py: centre.py,
  };
}

/** Resolves the view to use when browsing a series under an optional
 *  physical-scale lock (Stage/Compare share this — plan item 8):
 *  - locked (`targetScale` set) AND the image is calibrated (`pixelSize`
 *    finite and > 0) → hold physical scale, keep the given centre
 *  - otherwise (lock off, or an uncalibrated image: null/0/non-finite
 *    pixelSize) → `fitView`, exactly as the no-lock / no-calibration
 *    path has always behaved. */
export function resolveScaleView(
  targetScale: number | null,
  pixelSize: number | null,
  img: Size,
  vp: Size,
  keepCentre: { px: number; py: number },
): View {
  if (
    targetScale != null &&
    pixelSize != null &&
    Number.isFinite(pixelSize) &&
    pixelSize > 0
  ) {
    return viewForPhysicalScale(targetScale, pixelSize, keepCentre);
  }
  return fitView(img, vp);
}

/** View that frames an image-space rectangle (box-zoom). */
export function viewForRect(
  a: { x: number; y: number },
  b: { x: number; y: number },
  img: Size,
  vp: Size,
): View {
  const w = Math.abs(b.x - a.x);
  const h = Math.abs(b.y - a.y);
  if (w < 2 || h < 2) return fitView(img, vp); // degenerate marquee
  return {
    z: clampZoom(Math.min(vp.w / w, vp.h / h)),
    px: (a.x + b.x) / 2 / img.w,
    py: (a.y + b.y) / 2 / img.h,
  };
}

/** Calibrated distance between two image-pixel points. */
export function physDist(
  a: { x: number; y: number },
  b: { x: number; y: number },
  pixelSize: number | null,
): { value: number; unit: "px" | "cal" } {
  const d = Math.hypot(b.x - a.x, b.y - a.y);
  return pixelSize != null
    ? { value: d * pixelSize, unit: "cal" }
    : { value: d, unit: "px" };
}

export interface PolygonStats {
  areaPx2: number;
  centroid: { x: number; y: number };
  perimeterPx: number;
}

/** Shoelace area + centroid + perimeter over IMAGE-PIXEL points (use
 *  polygonStatsNormalized for the Measure.pts 0-1 convention). Shared by
 *  the polygon AND lasso measure kinds.
 *  - < 3 points → an all-zero result (never NaN).
 *  - A duplicated closing point (pts[last] === pts[0]) is NOT
 *    double-counted: the loop always wraps i → i+1 (mod n), so a
 *    repeated last vertex just contributes one zero-length edge.
 *  - Non-convex simple polygons are exact — this is full shoelace, not a
 *    convex-hull approximation.
 *  - Self-intersecting input (e.g. a bowtie) gets the SIGNED shoelace
 *    result as-is: crossing lobes can partially or fully cancel. This is
 *    intentional and NOT corrected; a caller needing a "true" area for
 *    self-intersecting polygons must simplify the outline first. */
export function polygonStats(pts: { x: number; y: number }[]): PolygonStats {
  const n = pts.length;
  if (n < 3) return { areaPx2: 0, centroid: { x: 0, y: 0 }, perimeterPx: 0 };

  let signedArea2 = 0; // 2x signed area (raw shoelace sum)
  let cx = 0;
  let cy = 0;
  let perimeterPx = 0;
  for (let i = 0; i < n; i++) {
    const a = pts[i];
    const b = pts[(i + 1) % n];
    const cross = a.x * b.y - b.x * a.y;
    signedArea2 += cross;
    cx += (a.x + b.x) * cross;
    cy += (a.y + b.y) * cross;
    perimeterPx += Math.hypot(b.x - a.x, b.y - a.y);
  }
  if (signedArea2 === 0) {
    // degenerate (collinear / zero-enclosed-area) — the centroid formula
    // divides by signedArea2, so fall back to the plain vertex average
    const avg = pts.reduce(
      (s, p) => ({ x: s.x + p.x / n, y: s.y + p.y / n }),
      { x: 0, y: 0 },
    );
    return { areaPx2: 0, centroid: avg, perimeterPx };
  }
  return {
    areaPx2: Math.abs(signedArea2) / 2,
    centroid: { x: cx / (3 * signedArea2), y: cy / (3 * signedArea2) },
    perimeterPx,
  };
}

/** polygonStats over NORMALIZED 0-1 points + image dimensions — the
 *  Measure.pts convention (viewerTypes.ts). Denormalizes then delegates;
 *  areaPx2/perimeterPx come back in image pixels, same as polygonStats. */
export function polygonStatsNormalized(
  pts: { x: number; y: number }[],
  img: Size,
): PolygonStats {
  return polygonStats(pts.map((p) => ({ x: p.x * img.w, y: p.y * img.h })));
}

/** px² → physical area via pixel_size² — ASSUMES SQUARE PIXELS, the
 *  project's pixel_cal convention (one scalar pixel_size for both axes;
 *  see calc/particles.py RegionStats.area_calibrated). null pixelSize
 *  (uncalibrated) → null, mirroring physDist's px/cal split. */
export function areaPxToPhysical(
  areaPx2: number,
  pixelSize: number | null,
): number | null {
  return pixelSize != null ? areaPx2 * pixelSize * pixelSize : null;
}

/** Per-image stage-tilt correction settings (#34). angle 0 = off. */
export interface TiltSettings {
  angle: number; // degrees, (−90, 90) exclusive; 0 = correction off
  axis: "X" | "Y";
  geometry: "cross-section" | "surface";
  /** stage tilt detected in file metadata — shown as a one-click
   *  "apply" hint in the Tilt card; never auto-applied */
  seedAngle?: number;
}

/** Tilt-corrected distance — mirrors calc/profiles.measure_distance:
 *  the in-tilt-axis component scales by 1/sin θ (cross-section) or
 *  1/cos θ (surface). Sign of θ is irrelevant (component is squared);
 *  θ=0 → plain physDist (avoids 1/sin(0)). */
export function tiltDist(
  a: { x: number; y: number },
  b: { x: number; y: number },
  pixelSize: number | null,
  tilt: TiltSettings | null,
): { value: number; unit: "px" | "cal" } {
  if (!tilt || tilt.angle === 0) return physDist(a, b, pixelSize);
  let dx = b.x - a.x;
  let dy = b.y - a.y;
  const rad = (tilt.angle * Math.PI) / 180;
  const f = tilt.geometry === "surface" ? 1 / Math.cos(rad) : 1 / Math.sin(rad);
  if (tilt.axis === "X") dx *= f;
  else dy *= f;
  const d = Math.hypot(dx, dy);
  return pixelSize != null
    ? { value: d * pixelSize, unit: "cal" }
    : { value: d, unit: "px" };
}

/** Angle at vertex v between rays v→a and v→b, in degrees [0, 180]. */
export function physAngle(
  v: { x: number; y: number },
  a: { x: number; y: number },
  b: { x: number; y: number },
): number {
  const a1 = Math.atan2(a.y - v.y, a.x - v.x);
  const a2 = Math.atan2(b.y - v.y, b.x - v.x);
  let deg = Math.abs(((a1 - a2) * 180) / Math.PI);
  if (deg > 180) deg = 360 - deg;
  return deg;
}

/** Box-profile geometry: a dragged box becomes a profile along its
 *  LONG axis, ⊥-averaged over the short axis (more signal than a 1-px
 *  line). Returns null for degenerate boxes (< 2 px either side). */
export function boxProfileLine(
  a: { x: number; y: number },
  b: { x: number; y: number },
): {
  p0: { x: number; y: number };
  p1: { x: number; y: number };
  width: number;
} | null {
  const w = Math.abs(b.x - a.x);
  const h = Math.abs(b.y - a.y);
  if (w < 2 || h < 2) return null;
  const horizontal = w >= h;
  const cx = (a.x + b.x) / 2;
  const cy = (a.y + b.y) / 2;
  return horizontal
    ? {
        p0: { x: Math.min(a.x, b.x), y: cy },
        p1: { x: Math.max(a.x, b.x), y: cy },
        width: Math.max(1, Math.round(h)),
      }
    : {
        p0: { x: cx, y: Math.min(a.y, b.y) },
        p1: { x: cx, y: Math.max(a.y, b.y) },
        width: Math.max(1, Math.round(w)),
      };
}

/** Length-unit factor to nm for the units the scale bar offers
 *  (Å / nm / µm, tolerant of ASCII spellings); null = not convertible
 *  (e.g. reciprocal-space "1/nm" calibrations). */
export function unitToNm(u: string): number | null {
  const s = u.trim().toLowerCase().replace("μ", "µ");
  if (s === "å" || s === "a" || s === "ang" || s === "angstrom") return 0.1;
  if (s === "nm") return 1;
  if (s === "µm" || s === "um") return 1000;
  return null;
}

/** Nice round scale-bar length: largest of 1/2/5×10ⁿ below `maxPhys`. */
export function niceScaleLength(maxPhys: number): number {
  const exp = Math.floor(Math.log10(maxPhys));
  const base = Math.pow(10, exp);
  for (const m of [5, 2, 1]) {
    if (m * base <= maxPhys) return m * base;
  }
  return base / 2;
}
