// The rasterized mask of the region being previewed, drawn 1:1 over the
// image: an SVG <image> placed at the mask's bounding box in screen space.
// The PNG stays a plain 8-bit mask (255 inside, 0 outside); a colour-matrix
// filter turns its luminance into the alpha of a tint, so the backend never
// has to know what colour the UI paints with. Pixelated, so a zoomed-in
// pixel is a square rather than a blur — the point of the preview is the
// boundary.

import { useId } from "react";

import { imageToScreen, type Size } from "../../lib/geometry";
import { useRegionPreviewStore } from "../../store/regionPreview";
import type { View } from "../../store/viewer";

/** Amber, distinct from every region-class colour the overlay draws with. */
export const MASK_PREVIEW_RGB: [number, number, number] = [0.961, 0.62, 0.043];
export const MASK_PREVIEW_OPACITY = 0.45;

/** Screen box of a 1-based inclusive (r1, c1, r2, c2) pixel rectangle: from
 *  the outer edge of its first pixel to the outer edge of its last, in the
 *  image frame where pixel k (0-based) spans [k, k + 1]. */
export function maskPreviewBox(
  rect: [number, number, number, number],
  view: View,
  img: Size,
  vp: Size,
): { x: number; y: number; width: number; height: number } {
  const [r1, c1, r2, c2] = rect;
  const a = imageToScreen(c1 - 1, r1 - 1, view, img, vp);
  const b = imageToScreen(c2, r2, view, img, vp);
  return { x: a.x, y: a.y, width: b.x - a.x, height: b.y - a.y };
}

/** feColorMatrix values: constant RGB, alpha = opacity × input red. */
export function tintMatrix(
  [r, g, b]: [number, number, number],
  opacity: number,
): string {
  return [
    `0 0 0 0 ${r}`,
    `0 0 0 0 ${g}`,
    `0 0 0 0 ${b}`,
    `${opacity} 0 0 0 0`,
  ].join("  ");
}

export default function MaskPreviewOverlay({
  imageId,
  view,
  img,
  vp,
}: {
  imageId: string;
  view: View;
  img: Size;
  vp: Size;
}) {
  const mask = useRegionPreviewStore((state) => state.mask);
  const filterId = `mask-tint-${useId().replaceAll(":", "")}`;
  if (!mask || mask.imageId !== imageId) return null;
  const box = maskPreviewBox(mask.rect, view, img, vp);
  return (
    <svg
      className="fvd-measure-layer fvd-mask-preview-overlay"
      width={vp.w}
      height={vp.h}
      pointerEvents="none"
      aria-label="Exact region mask preview"
      data-region-ref={mask.regionRef}
    >
      <defs>
        <filter id={filterId} colorInterpolationFilters="sRGB">
          <feColorMatrix
            type="matrix"
            values={tintMatrix(MASK_PREVIEW_RGB, MASK_PREVIEW_OPACITY)}
          />
        </filter>
      </defs>
      <image
        href={mask.href}
        x={box.x}
        y={box.y}
        width={box.width}
        height={box.height}
        preserveAspectRatio="none"
        style={{ imageRendering: "pixelated" }}
        filter={`url(#${filterId})`}
      />
    </svg>
  );
}
