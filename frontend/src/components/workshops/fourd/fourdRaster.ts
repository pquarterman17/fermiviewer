// Pure helpers for the FourD workshop's two canvas panels (nav minimap +
// pattern view): drawing a Raster16 through a grayscale LUT, and previewing
// where the aperture ring's center sits when auto-center is on. Kept
// canvas-free (like lib/composite.ts) so both are unit-testable.

import { compositeChannels, type CompositeRaster } from "../../../lib/composite";
import type { FourDAperture } from "../../../store/fourd";
import type { Raster16 } from "../../../lib/api";

/** Draw a single-channel Raster16 onto a canvas as grayscale, sizing the
 *  canvas to the raster's native pixel dims (CSS sizing/scaling is the
 *  caller's job, same division of labor as ChannelComposite). */
export function drawRaster16(canvas: HTMLCanvasElement, raster: Raster16): void {
  const cr: CompositeRaster = { w: raster.w, h: raster.h, data: raster.data };
  const { w, h, rgba } = compositeChannels(
    [cr],
    [{ color: "#ffffff", intensity: 1, visible: true, cmap: "gray" }],
  );
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const img = new ImageData(w, h);
  img.data.set(rgba);
  ctx.putImageData(img, 0, 0);
}

/** Intensity centroid of a raster: the finite-weighted first moment,
 *  mirroring `calc/fourd/geometry.pattern_center(method="centroid")`
 *  exactly (same fallback too) so the client preview and the server's
 *  authoritative center agree. Non-finite samples contribute zero weight;
 *  an all-zero (or non-positive-total) raster falls back to the geometric
 *  center `((h-1)/2, (w-1)/2)` — a degenerate pattern carries no
 *  information to seed a center from. Returns `(cy, cx)` in 0-based pixel
 *  coordinates, row-major `values[y * w + x]` like the rest of Raster16. */
export function rasterCentroid(
  values: ArrayLike<number>,
  w: number,
  h: number,
): { cy: number; cx: number } {
  const geometric = { cy: (h - 1) / 2, cx: (w - 1) / 2 };
  let total = 0;
  let sumY = 0;
  let sumX = 0;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const v = values[y * w + x];
      if (!Number.isFinite(v)) continue;
      total += v;
      sumY += v * y;
      sumX += v * x;
    }
  }
  if (total <= 0) return geometric;
  return { cy: sumY / total, cx: sumX / total };
}

/** Where to draw the aperture ring, in (row, col) pixel coords of the
 *  CURRENT pattern raster. When a manual center is set, that's authoritative.
 *  When auto-center is on, the server always centers on the MEAN pattern's
 *  intensity centroid (routes/fourd.py's compute-map path) — regardless of
 *  which pattern (mean or a probed one) is currently on screen — so the
 *  preview must use `meanRaster`, the mean pattern cached independently of
 *  whatever `displayedRaster` (the one actually drawn) currently is. Falls
 *  back to the displayed raster's geometric mid-point only when no mean
 *  pattern has been fetched yet. */
export function apertureCenterPreview(
  aperture: Pick<FourDAperture, "autoCenter" | "centerKy" | "centerKx">,
  displayedRaster: Pick<Raster16, "w" | "h"> | null,
  meanRaster: Raster16 | null = null,
): { cy: number; cx: number } | null {
  if (!aperture.autoCenter) {
    return aperture.centerKy != null && aperture.centerKx != null
      ? { cy: aperture.centerKy, cx: aperture.centerKx }
      : null;
  }
  if (meanRaster) {
    return rasterCentroid(meanRaster.data, meanRaster.w, meanRaster.h);
  }
  if (!displayedRaster) return null;
  return { cy: (displayedRaster.h - 1) / 2, cx: (displayedRaster.w - 1) / 2 };
}
