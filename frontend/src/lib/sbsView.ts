// Pure view-coupling logic for the side-by-side compare grid. Kept out of
// the React component so it can be unit-tested directly.
//
// When the panes are zoom-linked, a wheel-zoom on one pane propagates only
// the ZOOM LEVEL (z) to every OTHER pane — each pane keeps its own pan, so
// you can compare the same magnification at different regions. Pan and fit
// are always per-pane; unlinked, zoom is per-pane too.

import type { View } from "../store/viewer";

export type ViewChange = "zoom" | "pan" | "fit";

/** Compute the next per-pane view array after pane `idx` changed to `v`.
 *  `views` is the current array (entries may be null before first render);
 *  the returned array is a fresh copy with the acted-on pane set to `v` and,
 *  on a zoom-linked zoom, the other panes' z matched to v.z (pan preserved). */
export function nextGridViews(
  idx: number,
  v: View,
  kind: ViewChange,
  views: (View | null)[],
  zoomLinked: boolean,
): (View | null)[] {
  const out = views.slice();
  out[idx] = v;
  if (zoomLinked && kind === "zoom") {
    for (let i = 0; i < out.length; i++) {
      if (i === idx) continue;
      const cur = out[i] ?? v; // first-zoom: adopt the acted-on view's center
      out[i] = { ...cur, z: v.z };
    }
  }
  return out;
}
