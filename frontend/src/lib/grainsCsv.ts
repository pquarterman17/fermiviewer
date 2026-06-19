// CSV serialiser and overlay-PNG exporter for grain-analysis results.
// Pure builder functions (no DOM, no store) — the PNG export requires a
// browser Canvas and is kept as a self-contained helper so it can be called
// from the workshop component without coupling to the store.
//
// CSV columns follow the fields actually returned by /api/analyze/grains
// (GrainResult in api.ts): grain_id, area_px, perimeter_crofton_px,
// eccentricity — plus the global astm_grain_size in the header.

import type { GrainResult } from "./api";
import { renderUrl } from "./api";

// ── numeric formatter (matches profileCsv.ts convention) ─────────────

function num(v: number): string {
  if (!Number.isFinite(v)) return "";
  return String(Number(v.toPrecision(7)));
}

// ── CSV builder ───────────────────────────────────────────────────────

export interface GrainsCsvContext {
  imageName: string;
  method: string;
}

/**
 * Serialise a GrainResult to CSV.
 *
 * Columns: grain_id (1-based), area_px, perimeter_crofton_px, eccentricity.
 * A commented provenance header records image, method, n_grains,
 * mean_diameter_px, n_triple_junctions and (if calibrated) astm_grain_size.
 */
export function grainsToCsv(r: GrainResult, ctx: GrainsCsvContext): string {
  const lines: string[] = [
    "# fermiviewer grain export",
    `# image: ${ctx.imageName}`,
    `# method: ${ctx.method}`,
    `# n_grains: ${r.n_grains}`,
    `# mean_diameter_px: ${num(r.mean_diameter_px)}`,
    `# n_triple_junctions: ${r.n_triple_junctions}`,
    `# boundary_network_px: ${num(r.boundary_network_px)}`,
  ];
  if (r.astm_grain_size != null) {
    lines.push(`# astm_grain_size: ${num(r.astm_grain_size)}`);
  }
  lines.push("grain_id,area_px,perimeter_crofton_px,eccentricity");
  const n = r.areas_px.length;
  for (let i = 0; i < n; i++) {
    lines.push(
      `${i + 1},${num(r.areas_px[i])},${num(r.perimeters_px[i] ?? 0)},${num(r.eccentricity[i] ?? 0)}`,
    );
  }
  return lines.join("\n") + "\n";
}

// ── overlay PNG export ────────────────────────────────────────────────

/**
 * Composite the base image with the colorised grain-label map at native
 * resolution and trigger a browser download as PNG.
 *
 * @param baseImageId   Session ID of the original (greyscale) image.
 * @param labelsImageId Session ID of the colorised grain-label raster.
 * @param filename      Download filename.
 * @param alpha         Overlay blend opacity [0-1]; default 0.6.
 * @param onError       Called if either image fails to load.
 */
export function downloadGrainsOverlayPng(
  baseImageId: string,
  labelsImageId: string,
  filename = "grains_overlay.png",
  alpha = 0.6,
  onError?: (msg: string) => void,
): void {
  const loadImg = (src: string): Promise<HTMLImageElement> =>
    new Promise((resolve, reject) => {
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error(`failed to load ${src}`));
      img.src = src;
    });

  Promise.all([
    loadImg(renderUrl(baseImageId)),
    loadImg(renderUrl(labelsImageId)),
  ])
    .then(([base, overlay]) => {
      const w = base.naturalWidth;
      const h = base.naturalHeight;
      const canvas = document.createElement("canvas");
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext("2d");
      if (!ctx) {
        onError?.("canvas context unavailable");
        return;
      }
      // draw the greyscale base at full opacity
      ctx.drawImage(base, 0, 0, w, h);
      // blend the colorised label map on top
      ctx.globalAlpha = alpha;
      ctx.drawImage(overlay, 0, 0, w, h);
      ctx.globalAlpha = 1;
      canvas.toBlob((blob) => {
        if (!blob) {
          onError?.("canvas toBlob returned null");
          return;
        }
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
      });
    })
    .catch((e: Error) => onError?.(e.message));
}

/** Strip the extension off a filename for a CSV/PNG basename. */
export function csvBaseName(name: string | undefined): string {
  if (!name) return "image";
  return name.replace(/\.[^./\\]+$/, "") || name;
}

/** Trigger a browser download of CSV text. */
export function downloadCsv(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
