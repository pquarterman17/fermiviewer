// Extracted from lib/api.ts; public imports remain stable via the barrel.
import type { ImageMeta } from "./core";
import { post } from "./transport";

export interface EelsBackgroundResult {
  energy: number[];
  spectrum: number[];
  background: number[];
  signal: number[];
  params: Record<string, number>;
}

export function eelsBackground(
  id: string,
  fitWindow: [number, number],
  method = "powerlaw",
): Promise<EelsBackgroundResult> {
  return post("/api/eels/background", {
    image_id: id,
    fit_window: fitWindow,
    method,
  });
}

export function eelsMap(
  id: string,
  signalWindow: [number, number],
  backgroundWindow: [number, number] | null,
  method = "powerlaw",
): Promise<ImageMeta> {
  return post("/api/eels/map", {
    image_id: id,
    signal_window: signalWindow,
    background_window: backgroundWindow,
    method,
  });
}

// ── EELS advanced (thickness / KK / Fourier-log / SVD / align) ──────

export function eelsThickness(
  id: string,
  zlpWindow: [number, number] = [-5, 5],
): Promise<{
  map: ImageMeta;
  mean_t_over_lambda: number;
  valid_fraction: number;
}> {
  return post("/api/eels/thickness", { image_id: id, zlp_window: zlpWindow });
}

export interface KKResult {
  energy: number[];
  eps1: number[];
  eps2: number[];
  elf: number[];
  optical_conductivity: number[];
  refractive_index: number[];
  thickness_nm: number;
  t_over_lambda: number;
}

export function eelsKK(
  id: string,
  opts: {
    zlpWindow?: [number, number];
    refractiveIndex?: number;
    accKv?: number;
  } = {},
): Promise<KKResult> {
  return post("/api/eels/kk", {
    image_id: id,
    zlp_window: opts.zlpWindow ?? [-5, 5],
    refractive_index: opts.refractiveIndex ?? null,
    acc_voltage_kv: opts.accKv ?? 200,
  });
}

export function eelsFourierLog(
  id: string,
  zlpWindow: [number, number] = [-5, 5],
): Promise<{
  energy: number[];
  spectrum: number[];
  ssd: number[];
  t_over_lambda: number;
}> {
  return post("/api/eels/fourier-log", {
    image_id: id,
    zlp_window: zlpWindow,
  });
}

export function eelsSvd(
  id: string,
  opts: { nComponents?: number; denoise?: boolean; nScoreMaps?: number } = {},
): Promise<{
  explained: number[];
  cumulative: number[];
  energy: number[];
  eigenspectra: number[][];
  score_maps: ImageMeta[];
  denoised?: ImageMeta;
}> {
  return post("/api/eels/svd", {
    image_id: id,
    n_components: opts.nComponents ?? 0,
    denoise: opts.denoise ?? false,
    n_score_maps: opts.nScoreMaps ?? 4,
  });
}

export function eelsAlignZlp(
  id: string,
  window: [number, number] = [-20, 20],
): Promise<{
  aligned: ImageMeta;
  max_shift: number;
  shifted_fraction: number;
}> {
  return post("/api/eels/align-zlp", { image_id: id, window });
}

/** Sub-pixel ZLP alignment (#10): parabolic peak refine + fractional FFT
 *  shift. Registers the aligned cube as a derived spectrum-image. */
export function eelsSubpixelAlign(
  id: string,
  window: [number, number] = [-20, 20],
): Promise<{
  aligned: ImageMeta;
  max_shift: number;
  shifted_fraction: number;
}> {
  return post("/api/eels/subpixel-align", { image_id: id, window });
}

/** Richardson–Lucy deconvolution of the summed spectrum using its own ZLP
 *  as the point-spread function (#10) — recovers resolution lost to the
 *  ZLP. Returns the spectrum + deconvolved curve for an overlay. */
export function eelsRichardsonLucy(
  id: string,
  zlpWindow: [number, number] = [-5, 5],
  iterations = 15,
): Promise<{
  energy: number[];
  spectrum: number[];
  deconvolved: number[];
  iterations: number;
}> {
  return post("/api/eels/richardson-lucy", {
    image_id: id,
    zlp_window: zlpWindow,
    iterations,
  });
}

export interface EelsEdge {
  element: string;
  shell: string;
  z: number;
  onset_ev: number;
  signal_window: [number, number];
  bg_window: [number, number];
}

export interface EelsQuantResult {
  elements: string[];
  atomic_percent: number[];
  /** 1σ counting-statistics error on each at% (percentage points). */
  atomic_percent_error: number[];
  intensity: number[];
  sigma: number[];
}

export function eelsQuantify(
  id: string,
  edges: EelsEdge[],
  e0Kv = 200,
  betaMrad = 10,
  method = "powerlaw",
): Promise<EelsQuantResult> {
  return post("/api/eels/quantify", {
    image_id: id,
    edges,
    e0_kv: e0Kv,
    beta_mrad: betaMrad,
    method,
  });
}

/** Per-pixel SI composition maps (eelsQuantifyMap — upstream PR #25). */
export function eelsQuantifyMap(
  id: string,
  edges: EelsEdge[],
  e0Kv = 200,
  betaMrad = 10,
  method = "powerlaw",
): Promise<{
  elements: string[];
  mean_atomic_percent: number[];
  maps: ImageMeta[];
}> {
  return post("/api/eels/quantify-map", {
    image_id: id,
    edges,
    e0_kv: e0Kv,
    beta_mrad: betaMrad,
    method,
  });
}

/** One fitted edge from the model-based fit (PLAN_SPECTRAL_QUANT #2). */
export interface EelsFitEdge {
  element: string;
  shell: string;
  atomic_percent: number;
  /** 1σ on at% from the fit covariance (percentage points). */
  atomic_percent_error: number;
  amplitude: number;
  amplitude_error: number;
  curve: number[];
}

export interface EelsFitResult {
  energy: number[];
  spectrum: number[];
  model: number[];
  background: number[];
  edges: EelsFitEdge[];
  reduced_chi2: number;
  success: boolean;
}

/** Simultaneous background + multi-edge model fit of the summed spectrum.
 *  Returns at% from the fitted amplitude ratios, per-amplitude 1σ errors,
 *  and the fitted curves (model / background / per-edge) for an overlay. */
export function eelsFit(
  id: string,
  edges: EelsEdge[],
  e0Kv = 200,
  betaMrad = 10,
  fitRange: [number, number] | null = null,
): Promise<EelsFitResult> {
  return post("/api/eels/fit", {
    image_id: id,
    edges,
    e0_kv: e0Kv,
    beta_mrad: betaMrad,
    fit_range: fitRange,
  });
}

/** Per-pixel model fit over an SI cube; registers at% maps as derived images. */
export function eelsFitMap(
  id: string,
  edges: EelsEdge[],
  e0Kv = 200,
  betaMrad = 10,
  fitRange: [number, number] | null = null,
): Promise<{
  elements: string[];
  background_exponent: number;
  mean_atomic_percent: number[];
  maps: ImageMeta[];
}> {
  return post("/api/eels/fit-map", {
    image_id: id,
    edges,
    e0_kv: e0Kv,
    beta_mrad: betaMrad,
    fit_range: fitRange,
  });
}
