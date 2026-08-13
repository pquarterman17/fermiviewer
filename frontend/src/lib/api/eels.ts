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
export interface EelsQuantMapResult {
  elements: string[];
  sigma: number[];
  mean_atomic_percent: number[];
  maps: ImageMeta[];
}

export function eelsQuantifyMap(
  id: string,
  edges: EelsEdge[],
  e0Kv = 200,
  betaMrad = 10,
  method = "powerlaw",
): Promise<EelsQuantMapResult> {
  return post("/api/eels/quantify-map", {
    image_id: id,
    edges,
    e0_kv: e0Kv,
    beta_mrad: betaMrad,
    method,
  });
}

/** Queue an EELS composition map and return immediately with its job id. */
export function eelsQuantifyMapAsync(
  id: string,
  edges: EelsEdge[],
  e0Kv = 200,
  betaMrad = 10,
  method = "powerlaw",
): Promise<{ job_id: string }> {
  return post("/api/eels/quantify-map", {
    image_id: id,
    edges,
    e0_kv: e0Kv,
    beta_mrad: betaMrad,
    method,
    run_async: true,
  });
}

/** One fitted edge from the model-based fit (PLAN_SPECTRAL_QUANT #2). */
export interface EelsFitEdge {
  element: string;
  shell: string;
  /** Onset energy (eV), echoed back from the request (#7 / audit R8 —
   *  the fit-report CSV export's "center/onset" column). */
  onset_ev: number;
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
  /** Plain unweighted R² (1 − SS_res/SS_tot) over the ACTUAL fit window
   *  (calc/fit_quality.py via calc/eels_model.fit_edges) — not necessarily
   *  the full `energy` axis above. The residual trace itself is derived
   *  client-side from `spectrum`/`model` (lib/spectrum/fitQuality.ts). */
  r_squared: number;
  success: boolean;
  /** (e_lo, e_hi) actually optimised against — the resolved default when
   *  the request left `fit_range` unset (#7 / audit R8: the fit-report CSV
   *  export's header needs the real fit window, which is not always
   *  reconstructable client-side from `energy` alone). */
  fit_range: [number, number];
  /** Per-point 1σ of the total fitted model (delta method through the fit
   *  covariance + component Jacobian, calc/spectral_fit.model_sigma) — same
   *  length as `energy`/`model` above. `null` when the covariance was
   *  unusable (non-finite, or the fit didn't converge). Served rather than
   *  derived client-side (ANALYSIS_PRESENTATION_PLAN #3, following #2's
   *  convention): unlike the residual trace, a confidence band needs the
   *  covariance matrix and isn't reconstructable from what's already on
   *  the wire. */
  model_sigma: number[] | null;
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

// ── EELS edge auto-ID + batch maps (SPECTRAL_WORKSPACE_PLAN #22/#14) ────
// The Maps workflow's EELS half: identify() calls eelsAutoAssign once per
// cube, eelsMaps() extracts the ticked species in one round trip. Mirrors
// edsAutoAssign/edsElementMaps (lib/api/structure.ts, lib/api/eds.ts) in
// shape; see routes/eels_identify.py and routes/eels_maps.py for the
// response contracts these types describe.

export type EelsEdgeConfidence = "strong" | "clear" | "weak" | "trace";

export interface EelsAutoAssignEdge {
  element: string;
  edge: string;
  /** Combined "Fe-L23" label — element + edge joined by a dash. */
  symbol: string;
  onset_ev: number;
  fit_window: [number, number];
  signal_window: [number, number];
  net: number;
  sigma: number;
  significance: number;
  confidence: EelsEdgeConfidence;
}

export interface EelsAutoAssignResult {
  edges: EelsAutoAssignEdge[];
}

/** Edge-jump significance for every tabulated EELS edge the cube's energy
 *  axis can support — the EELS analogue of `edsAutoAssign`. Unlike EDS's
 *  candidate-only response, this one already carries net/sigma/significance/
 *  confidence per edge (see calc/eels_identify.py), sorted strongest first. */
export function eelsAutoAssign(
  id: string,
  opts: {
    fitWidthEv?: number;
    signalWidthEv?: number;
    fitGapEv?: number;
    method?: "powerlaw" | "exponential";
  } = {},
): Promise<EelsAutoAssignResult> {
  const body: Record<string, unknown> = { image_id: id };
  if (opts.fitWidthEv != null) body.fit_width_ev = opts.fitWidthEv;
  if (opts.signalWidthEv != null) body.signal_width_ev = opts.signalWidthEv;
  if (opts.fitGapEv != null) body.fit_gap_ev = opts.fitGapEv;
  if (opts.method != null) body.method = opts.method;
  return post("/api/eels/auto-assign", body);
}

/** One requested species for the batch maps endpoint — a label plus its
 *  integration windows, taken as given (no server-side line-energy lookup
 *  the way EDS's batch endpoint has). */
export interface EelsMapSpecRequest {
  label: string;
  signal: { lo: number; hi: number };
  background?: { lo: number; hi: number };
  method?: string;
}

/** One row of the batch response, aligned with the request by position. */
export interface EelsMapEntry {
  label: string;
  signal_window: [number, number] | null;
  background_window: [number, number] | null;
  method: string;
  map: number[][] | null;
  total_counts: number | null;
  map_meta: ImageMeta | null;
  /** Why this species could not be mapped, when it could not. Null on
   *  success — the row is kept either way. */
  error: string | null;
}

export interface EelsMapsResult {
  image_id: string;
  shape: [number, number];
  maps: EelsMapEntry[];
}

/** N species → N rasters in ONE request, without a full quantification —
 *  the EELS analogue of `edsElementMaps`. Prefer this over N concurrent
 *  `eelsMap` calls when populating a montage/overlay. */
export function eelsMaps(
  id: string,
  species: EelsMapSpecRequest[],
  opts: { saveDerived?: boolean; signal?: AbortSignal } = {},
): Promise<EelsMapsResult> {
  return post(
    "/api/eels/maps",
    { image_id: id, species, save_derived: opts.saveDerived ?? false },
    { signal: opts.signal },
  );
}
