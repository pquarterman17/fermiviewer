// Scan distortion correction: scan-line jitter within one image, and
// drift across a series of images (routes/jitter.py).
import type { ImageMeta } from "./core";
import { post } from "./transport";

export interface LineJitterResult {
  image: ImageMeta;
  /** Per-row horizontal offset (px); positive = the row sat to the right. */
  offsets: number[];
  rms: number;
  max_abs: number;
}

export function analyzeLineJitter(
  imageId: string,
  opts: { max_shift?: number; trend_rows?: number } = {},
): Promise<LineJitterResult> {
  return post("/api/analyze/line-jitter", { image_id: imageId, ...opts });
}

export interface FrameDriftResult {
  /** The drift-corrected average, cropped to the area every frame covers. */
  average: ImageMeta;
  /** Every aligned frame, when requested. */
  frames: ImageMeta[];
  /** Per-frame (dy, dx) drift (px) relative to the first frame. */
  shifts: [number, number][];
  max_abs: number;
  /** [top, bottom, left, right] of the crop, in first-frame pixels. */
  crop: [number, number, number, number];
}

export function analyzeFrameDrift(
  imageIds: string[],
  opts: { reference?: "mean" | "first"; crop?: boolean; keep_frames?: boolean } = {},
): Promise<FrameDriftResult> {
  return post("/api/analyze/frame-drift", { image_ids: imageIds, ...opts });
}
