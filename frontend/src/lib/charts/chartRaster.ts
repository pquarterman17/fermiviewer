// High-DPI PNG rasterisation for the chart SVG exporter
// (ANALYSIS_PRESENTATION_PLAN item 4). Split out of chartSvg.ts to keep
// that module under the repo's 500-line ceiling, and because this is the
// one piece of the export pipeline that needs a real browser Image/canvas
// round trip rather than pure string building.

import { DEFAULT_HEIGHT, DEFAULT_WIDTH } from "./chartSvg";

/**
 * Parse the `width`/`height` attributes chartToSvg always sets on the root
 * `<svg>` element, in CSS px. Pure string parsing — no DOM needed — so the
 * pixel math (dpi → target canvas size) is testable independent of
 * Image/canvas.
 */
export function parseSvgSize(svg: string): { width: number; height: number } {
  const w = /<svg[^>]*\bwidth="(\d+(?:\.\d+)?)"/.exec(svg);
  const h = /<svg[^>]*\bheight="(\d+(?:\.\d+)?)"/.exec(svg);
  return {
    width: w ? Number(w[1]) : DEFAULT_WIDTH,
    height: h ? Number(h[1]) : DEFAULT_HEIGHT,
  };
}

/**
 * Raster an SVG string to a PNG blob at `scale`× its declared CSS-pixel
 * size (e.g. scale = dpi/96 for a target DPI, since chartToSvg's width/
 * height attributes are on a 96-dpi CSS-px basis). Browser-only (Image +
 * canvas), following the same load-then-draw pattern as
 * lib/grainsCsv.ts's downloadGrainsOverlayPng — not unit-tested for the
 * same reason that function isn't: jsdom ships no real canvas/Image
 * pipeline (no `HTMLCanvasElement#getContext("2d")`, no image decoding),
 * so this is exercised live in the browser rather than under vitest.
 * `parseSvgSize` above carries the part of this that CAN be pure-tested.
 */
export function svgToPngBlob(svg: string, scale: number): Promise<Blob> {
  const { width, height } = parseSvgSize(svg);
  const pxWidth = Math.max(1, Math.round(width * scale));
  const pxHeight = Math.max(1, Math.round(height * scale));
  return new Promise((resolve, reject) => {
    const img = new Image();
    const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
    img.onload = () => {
      URL.revokeObjectURL(url);
      const canvas = document.createElement("canvas");
      canvas.width = pxWidth;
      canvas.height = pxHeight;
      const ctx = canvas.getContext("2d");
      if (!ctx) {
        reject(new Error("canvas 2D context unavailable"));
        return;
      }
      ctx.drawImage(img, 0, 0, pxWidth, pxHeight);
      canvas.toBlob((blob) => {
        if (blob) resolve(blob);
        else reject(new Error("PNG rasterisation failed"));
      }, "image/png");
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("could not rasterise the chart SVG"));
    };
    img.src = url;
  });
}
