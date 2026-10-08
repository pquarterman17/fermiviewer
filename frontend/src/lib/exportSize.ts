// Export output-size estimate + ceiling (ExportDialog summary line).
//
// Mirrors the backend /api/export geometry: the colorbar gutter
// (routes/_export_render.composite_colorbar / _export_svg.build_svg) and the
// caption band below the figure (draw_caption_band / _svg_caption_parts), so
// the "W × H px" the dialog shows matches the file that is written.

/** Server-side ceiling (routes/export.py MAX_EXPORT_SIDE / _PIXELS). */
export const MAX_EXPORT_SIDE = 20_000;
export const MAX_EXPORT_PIXELS = 16_384 * 16_384;

/** pad + strip + label gutter appended right of the figure for a colorbar. */
const COLORBAR_GUTTER = 81;

/** Greedy word-wrap line count, approximating the backend's TTF wrap with a
 *  monospace advance of 0.6 em (JetBrains Mono). */
function wrappedLines(text: string, maxW: number, font: number): number {
  const perLine = Math.max(1, Math.floor(maxW / (0.6 * font)));
  let n = 0;
  for (const raw of text.split("\n")) {
    if (!raw.trim()) continue;
    let cur = 0;
    for (const word of raw.split(" ")) {
      const trial = cur ? cur + 1 + word.length : word.length;
      if (!cur || trial <= perLine) cur = trial;
      else {
        n += 1;
        cur = word.length;
      }
    }
    n += 1;
  }
  return n;
}

/** Final W × H of an export whose figure is `w` × `h` px, adding the colorbar
 *  gutter and caption band the backend appends. `scale` is the effective
 *  export scale (float in physical mode). */
export function exportOutputSize(
  w: number,
  h: number,
  opts: {
    format: string;
    scale: number;
    colorbar: boolean;
    caption: string;
  },
): { w: number; h: number } {
  if (opts.format === "tiff16") return { w, h };
  const totalW = w + (opts.colorbar ? COLORBAR_GUTTER : 0);
  let band = 0;
  if (opts.caption.trim()) {
    if (opts.format === "svg") {
      // SVG caption: fixed 13 px font, one <text> per source line (no wrap)
      const n = opts.caption.split("\n").filter((l) => l.trim()).length;
      band = 12 + 17 * n;
    } else {
      const s = Math.max(1, Math.round(opts.scale));
      const font = Math.max(11, 13 * s);
      const pad = Math.max(6, 5 * s);
      const lineH = font + Math.max(2, 2 * s);
      const n = wrappedLines(opts.caption, totalW - 2 * pad, font);
      band = n ? pad * 2 + lineH * n : 0;
    }
  }
  return { w: totalW, h: h + band };
}

/** True when a w × h figure exceeds the backend export ceiling. */
export function exportTooLarge(w: number, h: number): boolean {
  return Math.max(w, h) > MAX_EXPORT_SIDE || w * h > MAX_EXPORT_PIXELS;
}
