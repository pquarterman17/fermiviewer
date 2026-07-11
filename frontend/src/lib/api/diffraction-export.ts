// Extracted from lib/api.ts; public imports remain stable via the barrel.
import { post } from "./transport";

export interface DetectResult {
  spots: [number, number][]; // 1-based (row, col)
  n: number;
}

export function diffractionDetect(
  id: string,
  opts: { minRadius?: number; threshold?: number; minSeparation?: number } = {},
): Promise<DetectResult> {
  return post("/api/diffraction/detect", {
    image_id: id,
    min_radius: opts.minRadius ?? 10,
    threshold: opts.threshold ?? 0.05,
    min_separation: opts.minSeparation ?? 8,
  });
}

/** Analysis region-of-interest — two shapes mirroring the backend _Roi model. */
export type AnalysisRoi =
  | { kind: "rect"; r0: number; c0: number; r1: number; c1: number }
  | { kind: "circle"; cr: number; cc: number; radius: number };

export interface PhaseCandidate {
  phase: string;
  formula: string;
  score: number;
  n_matched: number;
  matched_hkl: number[][];
  matched_d: number[];   // measured d-spacings for each matched spot (Å)
  ref_d: number[];       // reference d-spacings for each matched spot (Å)
  matched_idx: number[]; // index into the input spots[] for each matched spot
  zone_axis: number[];
}

export interface IndexResult {
  center: [number, number];   // [row, col] 1-based pattern centre
  measured_r: number[];       // px radius per spot (same order as input spots)
  candidates: PhaseCandidate[];
}

export function diffractionIndex(
  id: string,
  spots: [number, number][],
  opts: {
    pixelSizeMm?: number;
    cameraLengthMm?: number;
    accKv?: number;
    roi?: AnalysisRoi;
  } = {},
): Promise<IndexResult> {
  return post("/api/diffraction/index", {
    image_id: id,
    spots,
    pixel_size_mm: opts.pixelSizeMm ?? 1.0,
    camera_length_mm: opts.cameraLengthMm ?? null,
    acc_voltage_kv: opts.accKv ?? 200,
    roi: opts.roi ?? null,
  });
}

export function diffractionDetectWithRoi(
  id: string,
  opts: {
    minRadius?: number;
    threshold?: number;
    minSeparation?: number;
    maxSpots?: number;
    roi?: AnalysisRoi;
  } = {},
): Promise<DetectResult> {
  return post("/api/diffraction/detect", {
    image_id: id,
    min_radius: opts.minRadius ?? 10,
    threshold: opts.threshold ?? 0.05,
    min_separation: opts.minSeparation ?? 8,
    max_spots: opts.maxSpots ?? 50,
    roi: opts.roi ?? null,
  });
}

export interface ExportOptions {
  format: "png" | "tiff16" | "jpeg" | "svg" | "pdf";
  scale: number;
  // publication sizing (Quick-Wins #3): set BOTH to size the output to a
  // physical width (target px = width_mm/25.4 * dpi) and embed dpi, instead
  // of the integer scale. Omitted/either-null → the integer scale path.
  width_mm?: number | null;
  dpi?: number | null;
  lo: number; // normalized [0,1] window (display state)
  hi: number;
  gamma: number;
  cmap: string;
  include: string[]; // "scale_bar" | "measurements" | "colorbar" | "caption"
  // report caption burned below the figure (WS4c); frontend composes the
  // text (user caption + optional metadata line)
  caption?: string | null;
  measures?: {
    kind: string;
    pts: { x: number; y: number }[];
    text?: string;
    endSymbol?: string;
    width?: number; // box-profile ⊥ averaging width (image px)
  }[];
  overlay_color?: string;
  // measurement overlay styling (mirrors the on-screen overlay size + line
  // width); omitted → backend's legacy 2 px line / small fixed label
  overlay_font_size?: number | null;
  overlay_line_width?: number | null;
  // custom scale bar geometry (item #33); all optional — null → auto
  scale_bar_norm_x?: number | null;
  scale_bar_norm_y?: number | null;
  scale_bar_length_phys?: number | null;
  scale_bar_thickness?: number | null;
  // tilt correction for distance/profile/polyline labels (#34); 0 → off
  tilt_angle_deg?: number;
  tilt_axis?: "X" | "Y";
  tilt_geometry?: "cross-section" | "surface";
  // scale-bar label font size in screen px (#48); null → 20 (default)
  scale_bar_font_size?: number | null;
  // scale-bar bar + label colour (audit #10); null → "#ffffff" (white)
  scale_bar_color?: string | null;
  // force a label unit regardless of calibration (audit #10); null → auto
  scale_bar_unit_override?: string | null;
}

/** Server-side export; returns the file blob + suggested filename. */
export async function exportImage(
  id: string,
  opts: ExportOptions,
): Promise<{ blob: Blob; filename: string }> {
  const res = await fetch("/api/export", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ image_id: id, ...opts }),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = ((await res.json()) as { detail?: string }).detail ?? detail;
    } catch {
      /* binary or empty error body */
    }
    throw new Error(detail);
  }
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const match = /filename="([^"]+)"/.exec(disposition);
  return {
    blob: await res.blob(),
    filename: match?.[1] ?? `export.${opts.format === "tiff16" ? "tif" : opts.format}`,
  };
}
