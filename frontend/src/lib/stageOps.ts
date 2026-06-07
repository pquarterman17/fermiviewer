// Geometric stage operations (rotate / flip / crop-to-ROI) shared by
// the floating toolbar and the Image menu. All ops produce derived
// images via POST /filter and select the result.

import { applyFilter } from "./api";
import { useViewer } from "../store/viewer";

export type GeometryKind =
  | "rotate90"
  | "rotate270"
  | "rotate180"
  | "fliph"
  | "flipv";

/** Apply a parameterless geometric filter to the active image. */
export function applyGeometry(kind: GeometryKind): void {
  const s = useViewer.getState();
  if (!s.activeId) return;
  applyFilter(s.activeId, kind)
    .then((m) => {
      s.ingestDerived([m]);
      s.setStatus(`${kind} → ${m.name}`);
    })
    .catch((e: Error) => s.setStatus(`${kind}: ${e.message}`));
}

/** Crop the active image to its selected (or most recent) ROI
 *  measure. Returns false when no ROI exists. */
export function cropToRoi(): boolean {
  const s = useViewer.getState();
  const id = s.activeId;
  if (!id) return false;
  const meta = s.images[id];
  const rois = (s.measures[id] ?? []).filter((m) => m.kind === "roi");
  if (!meta || rois.length === 0) {
    s.setStatus("crop: draw an ROI first (R)");
    return false;
  }
  const roi = rois.find((m) => m.id === s.selectedMeasure) ?? rois[rois.length - 1];
  const [h, w] = meta.shape;
  // normalized 0–1 → 1-based inclusive pixel rect (backend convention)
  const px = (v: number, n: number) =>
    Math.min(n, Math.max(1, Math.round(v * n + 0.5)));
  applyFilter(id, "crop", {
    row0: px(roi.pts[0].y, h),
    col0: px(roi.pts[0].x, w),
    row1: px(roi.pts[1].y, h),
    col1: px(roi.pts[1].x, w),
  })
    .then((m) => {
      s.ingestDerived([m]);
      s.setStatus(`crop → ${m.name}`);
    })
    .catch((e: Error) => s.setStatus(`crop: ${e.message}`));
  return true;
}
