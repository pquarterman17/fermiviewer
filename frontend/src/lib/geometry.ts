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

/** Nice round scale-bar length: largest of 1/2/5×10ⁿ below `maxPhys`. */
export function niceScaleLength(maxPhys: number): number {
  const exp = Math.floor(Math.log10(maxPhys));
  const base = Math.pow(10, exp);
  for (const m of [5, 2, 1]) {
    if (m * base <= maxPhys) return m * base;
  }
  return base / 2;
}
