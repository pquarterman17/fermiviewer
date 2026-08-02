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

/** Where to draw the aperture ring, in (row, col) pixel coords of the
 *  CURRENT pattern raster. When a manual center is set, that's authoritative.
 *  When auto-center is on this is a client-side PREVIEW only — it uses the
 *  geometric mid-point, the same fallback formula
 *  `calc/fourd/geometry.pattern_center` uses for a degenerate pattern; the
 *  server computes the true intensity-weighted centroid from the full
 *  float64 mean pattern when Compute map actually runs. */
export function apertureCenterPreview(
  aperture: Pick<FourDAperture, "autoCenter" | "centerKy" | "centerKx">,
  raster: Pick<Raster16, "w" | "h"> | null,
): { cy: number; cx: number } | null {
  if (!aperture.autoCenter) {
    return aperture.centerKy != null && aperture.centerKx != null
      ? { cy: aperture.centerKy, cx: aperture.centerKx }
      : null;
  }
  if (!raster) return null;
  return { cy: (raster.h - 1) / 2, cx: (raster.w - 1) / 2 };
}
