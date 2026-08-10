// Pure view-coupling logic for the side-by-side compare grid. Kept out of
// the React component so it can be unit-tested directly.
//
// When the panes are zoom-linked, a wheel-zoom on one pane propagates to
// every OTHER pane — each pane keeps its own pan, so you can compare the
// same magnification at different regions. Pan and fit are always
// per-pane; unlinked, zoom is per-pane too.
//
// #9: "same magnification" means the same PHYSICAL scale (pixel_unit per
// screen px — lib/geometry.ts physicalScale), not the same raw `z`. Panes
// showing images calibrated at different pixel sizes must still show a
// feature at the same on-screen size once linked. When either the
// acted-on pane or a given other pane is uncalibrated, that pane falls
// back to matching raw `z` — the pre-#9 behaviour — since there is no
// physical scale to hold.

import type { View } from "../store/viewer";
import { clampZoom, physicalScale } from "./geometry";

export type ViewChange = "zoom" | "pan" | "fit";

const calibrated = (px: number | null | undefined): px is number =>
  px != null && Number.isFinite(px) && px > 0;

/** Compute the next per-pane view array after pane `idx` changed to `v`.
 *  `views` is the current array (entries may be null before first render);
 *  the returned array is a fresh copy with the acted-on pane set to `v` and,
 *  on a zoom-linked zoom, the other panes' z matched to v's physical scale
 *  (pan preserved). `pixelSizes` is parallel to `views` — each pane's
 *  `pixel_unit` per image px, or null/omitted when uncalibrated; omitting
 *  it entirely reproduces the pre-#9 raw-z matching for every pane. */
export function nextGridViews(
  idx: number,
  v: View,
  kind: ViewChange,
  views: (View | null)[],
  zoomLinked: boolean,
  pixelSizes: (number | null)[] = [],
): (View | null)[] {
  const out = views.slice();
  out[idx] = v;
  if (zoomLinked && kind === "zoom") {
    const actedPixelSize = pixelSizes[idx];
    // the target physical scale to hold, or null when it can't be computed
    // (acted-on pane uncalibrated) — every other pane then falls back to z
    const targetScale = calibrated(actedPixelSize)
      ? physicalScale(v, actedPixelSize)
      : null;
    for (let i = 0; i < out.length; i++) {
      if (i === idx) continue;
      const cur = out[i] ?? v; // first-zoom: adopt the acted-on view's center
      const ps = pixelSizes[i];
      out[i] =
        targetScale != null && calibrated(ps)
          ? { ...cur, z: clampZoom(ps / targetScale) }
          : { ...cur, z: v.z };
    }
  }
  return out;
}
