// Extracted from lib/api.ts; public imports remain stable via the barrel.
import { recordPathOp } from "../macro";
import type { ImageMeta } from "./core";
import { json, post } from "./transport";

// ── item-28 analysis surface ────────────────────────────────────────

/** Apply a server-side filter; returns the derived image's meta. */
export function applyFilter(
  id: string,
  kind: string,
  params: Record<string, unknown> = {},
): Promise<ImageMeta> {
  return post("/api/filter", { image_id: id, kind, params });
}

/** Log-magnitude FFT registered as a derived image. Optional 1-based
 *  rect computes the LOCAL FFT of that region (live-FFT). */
export async function imageFft(
  id: string,
  rect?: [number, number, number, number],
): Promise<ImageMeta> {
  recordPathOp("/api/image/{id}/fft"); // macro capture
  return json(
    await fetch(`/api/image/${id}/fft`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(rect ? { rect } : {}),
    }),
  );
}

/** Masked-FFT inverse (Fourier filter). Masks are (row, col, radius)
 *  in 1-based FFT pixels; the backend mirrors conjugate-symmetric
 *  partners. Returns the filtered real-space derived image. */
export function analyzeFftMask(
  id: string,
  masks: [number, number, number][],
  mode: "pass" | "reject",
): Promise<{ image: ImageMeta }> {
  return post("/api/analyze/fft-mask", { image_id: id, masks, mode });
}

export function analyzeRadial(
  id: string,
  opts: {
    azimuthal?: boolean;
    sectorMin?: number;
    sectorMax?: number;
  } = {},
): Promise<{
  radii: number[];
  intensity: (number | null)[];
  unit: string;
}> {
  return post("/api/analyze/radial", {
    image_id: id,
    azimuthal: opts.azimuthal ?? false,
    sector_min: opts.sectorMin ?? 0,
    sector_max: opts.sectorMax ?? 360,
  });
}

export function analyzeVdf(
  id: string,
  center: [number, number],
  radius: number,
): Promise<{ image: ImageMeta }> {
  return post("/api/analyze/vdf", { image_id: id, center, radius });
}

export function analyzeGpa(
  id: string,
  g1: [number, number],
  g2: [number, number],
): Promise<{ maps: ImageMeta[]; mean: Record<string, number> }> {
  return post("/api/analyze/gpa", { image_id: id, g1, g2 });
}

export interface ParticleRow {
  id: number;
  area: number;
  centroid: [number, number];
  equiv_diameter: number;
  mean_intensity: number;
  area_calibrated: number | null;
  diameter_calibrated: number | null;
}

export function analyzeParticles(
  id: string,
  opts: {
    threshold?: number | null;
    minArea?: number;
    watershed?: boolean;
    polarity?: "bright" | "dark";
  },
): Promise<{
  n_particles: number;
  threshold: number;
  labels: ImageMeta;
  particles: ParticleRow[];
  unit: string;
}> {
  return post("/api/analyze/particles", {
    image_id: id,
    threshold: opts.threshold ?? null,
    min_area: opts.minArea ?? 1,
    use_watershed: opts.watershed ?? false,
    polarity: opts.polarity ?? "bright",
  });
}

export interface JobStatus {
  id: string;
  status: "queued" | "running" | "done" | "error";
  progress: number;
  message: string;
  result?: unknown;
  error?: string;
}

/** Start an async job; poll until done; reports progress via callback. */
export async function runJob<T>(
  start: () => Promise<{ job_id: string }>,
  onProgress: (fraction: number, message: string) => void,
  pollMs = 400,
): Promise<T> {
  const { job_id } = await start();
  for (;;) {
    const s = await json<JobStatus>(await fetch(`/api/jobs/${job_id}`));
    if (s.status === "done") return s.result as T;
    if (s.status === "error") throw new Error(s.error ?? "job failed");
    onProgress(s.progress, s.message);
    await new Promise((r) => setTimeout(r, pollMs));
  }
}

export type GrainMethod =
  | "kmeans"
  | "gradient"
  | "rag"
  | "orientation"
  | "trained";

export interface GrainParams {
  method: GrainMethod;
  roi?: [number, number, number, number] | null;
  k?: number;
  granularity?: number;
  compactness?: number;
  orientation_sigma?: number;
  n_superpixels?: number;
  merge_threshold?: number;
  min_area?: number;
  /** Gaussian denoise σ (px) before watershed — suppresses noise over-segmentation */
  denoise_sigma?: number;
  /** outlier-rejecting percentile contrast stretch (default true) */
  robust?: boolean;
}

export interface GrainResult {
  n_grains: number;
  method: GrainMethod;
  labels: ImageMeta;
  mean_diameter_px: number;
  boundary_length_px: number;
  /** true grain-boundary network length (border-excluding inter-grain edges) */
  boundary_network_px: number;
  boundary_length_calibrated: number | null;
  n_boundary_segments: number;
  n_triple_junctions: number;
  /** ASTM E112 grain-size number; null when uncalibrated */
  astm_grain_size: number | null;
  areas_px: number[];
  perimeters_px: number[];
  eccentricity: number[];
  unit: string;
}

export function analyzeGrainsAsync(
  id: string,
  params: GrainParams,
): Promise<{ job_id: string }> {
  return post("/api/analyze/grains", {
    image_id: id,
    run_async: true,
    ...params,
  });
}

export function analyzeGrains(
  id: string,
  params: GrainParams,
): Promise<GrainResult> {
  return post("/api/analyze/grains", { image_id: id, ...params });
}

/** Interactive edit of a grain-label map: merge ≥2 clicked grains, or split
 *  the grain under the (first) click. Returns a fresh, still-editable map. */
export function grainsEdit(
  labelsId: string,
  op: "merge" | "split",
  points: [number, number][],
  granularity = 0.03,
): Promise<GrainResult> {
  return post("/api/grains/edit", {
    labels_id: labelsId,
    op,
    points,
    granularity,
  });
}

/** One painted scribble: a polyline (image coords) of a given brush radius
 *  labelling pixels as `class_id`. */
export interface TrainStroke {
  class_id: number;
  radius: number;
  points: [number, number][];
}

export interface TrainSegmentOpts {
  roi?: [number, number, number, number] | null;
  scales?: number[];
  gradientSigma?: number;
  minArea?: number;
  boundaryClass?: number[];
  /** "softmax" (linear, default) or "forest" (nonlinear random forest, #8) */
  classifier?: "softmax" | "forest";
}

/** Scribble-trained grain segmentation (parity #8): fit a pixel classifier
 *  on the painted strokes, apply it to the whole image, and return an
 *  editable grain-label map (same shape as analyzeGrains). */
export function grainsTrainSegment(
  id: string,
  strokes: TrainStroke[],
  opts: TrainSegmentOpts = {},
): Promise<GrainResult> {
  return post("/api/grains/train-segment", {
    image_id: id,
    roi: opts.roi ?? null,
    strokes,
    scales: opts.scales ?? [2, 4],
    gradient_sigma: opts.gradientSigma ?? 0,
    min_area: opts.minArea ?? 25,
    boundary_class: opts.boundaryClass ?? [],
    classifier: opts.classifier ?? "softmax",
  });
}

/** One predicted class in a trained-grain preview: its id, the fraction of the
 *  image it covers (0..1), and whether it was flagged boundary/background. */
export interface GrainPreviewClass {
  class_id: number;
  fraction: number;
  is_boundary: boolean;
}

export interface GrainPreview {
  classes: GrainPreviewClass[];
}

/** Optional, non-committing preview of the trained pixel classifier: fit on
 *  the painted strokes and report the per-class pixel composition, WITHOUT
 *  labelling grains or registering any image. Lets the user check the split
 *  before committing with grainsTrainSegment. */
export function grainsTrainPreview(
  id: string,
  strokes: TrainStroke[],
  opts: {
    roi?: [number, number, number, number] | null;
    scales?: number[];
    gradientSigma?: number;
    boundaryClass?: number[];
    classifier?: "softmax" | "forest";
  } = {},
): Promise<GrainPreview> {
  return post("/api/grains/train-preview", {
    image_id: id,
    roi: opts.roi ?? null,
    strokes,
    scales: opts.scales ?? [2, 4],
    gradient_sigma: opts.gradientSigma ?? 0,
    boundary_class: opts.boundaryClass ?? [],
    classifier: opts.classifier ?? "softmax",
  });
}
