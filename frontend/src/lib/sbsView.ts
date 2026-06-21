// Pure view-coupling logic for side-by-side compare. Kept out of the React
// component so it can be unit-tested directly.
//
// When the two panes are zoom-linked, a wheel-zoom on one pane propagates
// only the ZOOM LEVEL (z) to the other — each pane keeps its own pan, so you
// can compare the same magnification at different regions. Pan and fit are
// always per-pane; unlinked, zoom is per-pane too.

import type { SbsPane, View } from "../store/viewer";

export type ViewChange = "zoom" | "pan" | "fit";

export function nextSbsViews(
  pane: SbsPane,
  v: View,
  kind: ViewChange,
  viewL: View | null,
  viewR: View | null,
  zoomLinked: boolean,
): { viewL: View | null; viewR: View | null } {
  // couple only the zoom level, and only on a zoom gesture
  if (zoomLinked && kind === "zoom") {
    if (pane === "L") {
      return { viewL: v, viewR: { ...(viewR ?? v), z: v.z } };
    }
    return { viewL: { ...(viewL ?? v), z: v.z }, viewR: v };
  }
  // pan / fit / unlinked-zoom → only the acted-on pane moves
  return pane === "L" ? { viewL: v, viewR } : { viewL, viewR: v };
}
