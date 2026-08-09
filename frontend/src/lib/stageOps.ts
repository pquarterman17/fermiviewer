// Geometric stage operations (rotate / flip / crop-to-ROI) shared by
// the floating toolbar and the Image menu. All ops produce derived
// images via POST /filter and select the result.

import { applyFilter, stripDatabar as stripDatabarApi, type ImageMeta } from "./api";
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

/** Rows of real image above a vendor-baked databar, or null when there is
 *  nothing to strip. Pure and meta-taking so the Image menu can derive its
 *  disabled state from the store slice it already subscribes to, instead of
 *  a getState() read that wouldn't re-render it. Re-checks the row count
 *  against the array height so a stale or bogus tag can't drive a crop. */
export function databarRows(meta: ImageMeta | undefined): number | null {
  const rows = meta?.content_rows;
  if (meta == null || rows == null) return null;
  return rows > 0 && rows < meta.shape[0] ? rows : null;
}

/** True when the active image has a vendor-baked databar to strip. */
export function hasDatabar(): boolean {
  const s = useViewer.getState();
  return databarRows(s.activeId ? s.images[s.activeId] : undefined) != null;
}

/** Crop the vendor databar off the active image (Thermo Fisher SEM/FIB).
 *  The server owns the cut geometry — it read the vendor tags — so this
 *  sends no rect. Returns false when there is no bar to strip. */
export function stripDatabar(): boolean {
  const s = useViewer.getState();
  const id = s.activeId;
  if (!id) return false;
  if (!hasDatabar()) {
    s.setStatus("no vendor databar on this image");
    return false;
  }
  stripDatabarApi(id)
    .then((m) => {
      s.ingestDerived([m]);
      s.setStatus(`databar stripped → ${m.name}`);
    })
    .catch((e: Error) => s.setStatus(`strip databar: ${e.message}`));
  return true;
}
