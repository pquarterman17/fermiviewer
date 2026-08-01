// Post-edit analysis refresh (on handle release) — split out of
// MeasureOverlay.tsx to keep that drag-heavy SVG component under the
// frontend size ratchet. Reads only stable store actions plus the ctx
// passed in; no refs, no drag state.

import {
  measurePolyline,
  measureProfile,
  measureRoi,
  type RoiStats,
} from "../../lib/api";
import type { Size, TiltSettings } from "../../lib/geometry";
import type { ActiveProfile } from "../../store/stage";
import { useViewer, type Measure } from "../../store/viewer";
import { toImagePx } from "./measureGlyphs";

export interface MeasureRefreshCtx {
  imageId: string;
  img: Size;
  tilt: TiltSettings | null;
  setProfile: (p: ActiveProfile | null) => void;
  setStatus: (msg: string) => void;
  setRoiStats: (measureId: string, stats: RoiStats) => void;
}

/** Fires the right measure/{profile,roi} API call after a handle drag ends,
 *  and feeds the result back into the active-profile / ROI-stats stores. */
export function useMeasureRefresh(ctx: MeasureRefreshCtx) {
  const { imageId, img, tilt, setProfile, setStatus, setRoiStats } = ctx;
  return (m: Measure) => {
    const px = toImagePx(m, img);
    // box-profile measures carry their own ⊥ width (the box's short axis)
    const width = m.width ?? useViewer.getState().profileWidth;
    const reduce = useViewer.getState().profileReduce;
    if (m.kind === "profile") {
      measureProfile(imageId, px[0], px[1], width, tilt, reduce)
        .then((r) => setProfile({ ...r, measureId: m.id }))
        .catch((e: Error) => setStatus(e.message));
    } else if (m.kind === "polyline") {
      measurePolyline(imageId, px, width, reduce)
        .then((r) => setProfile({ ...r, measureId: m.id }))
        .catch((e: Error) => setStatus(e.message));
    } else if (m.kind === "roi" || m.kind === "ellipse") {
      measureRoi(
        imageId,
        px[0],
        px[1],
        m.kind === "ellipse" ? "ellipse" : "rect",
      )
        .then((r) => setRoiStats(m.id, r))
        .catch((e: Error) => setStatus(e.message));
    }
  };
}
