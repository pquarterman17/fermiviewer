// Extracted from lib/api.ts; public imports remain stable via the barrel.
import type { ImageMeta } from "./core";
import { json, post } from "./transport";

export interface EdsQuantResult {
  elements: string[];
  lines: string[];
  mean_atomic_pct: number[];
  mean_weight_pct: number[];
  /** Aggregate counting-statistics 1σ on the field composition (pct points). */
  mean_atomic_pct_error: number[];
  mean_weight_pct_error: number[];
  k_factors: number[];
  /** One at% map per element, aligned with `elements`; null where the map is
   *  blank (element not really present) and was skipped to keep the library clean. */
  maps: (ImageMeta | null)[];
}

export function edsQuantify(
  id: string,
  elements: string[],
  opts: {
    method?: "cliff-lorimer" | "zaf";
    thicknessNm?: number;
    takeOffAngleDeg?: number;
  } = {},
): Promise<EdsQuantResult> {
  return post("/api/eds/quantify", {
    image_id: id,
    elements,
    method: opts.method ?? "cliff-lorimer",
    thickness_nm: opts.thicknessNm ?? 100,
    take_off_angle_deg: opts.takeOffAngleDeg ?? 20,
  });
}

// ── EDS model-based fit (PLAN_SPECTRAL_QUANT #4/#5) ──────────────────

export interface EdsContinuumResult {
  energy: number[];
  spectrum: number[];
  continuum: number[];
  amp: number;
  absorption: number;
  reduced_chi2: number;
  success: boolean;
}

/** Fit the Kramers bremsstrahlung continuum to the summed spectrum,
 *  masking the named elements' characteristic peaks (#4). */
export function edsContinuum(
  id: string,
  e0Kev: number,
  opts: {
    excludeLines?: string[];
    excludeWindows?: [number, number][];
    fitAbsorption?: boolean;
    weights?: "poisson" | null;
  } = {},
): Promise<EdsContinuumResult> {
  return post("/api/eds/continuum", {
    image_id: id,
    e0_kev: e0Kev,
    exclude_lines: opts.excludeLines ?? [],
    exclude_windows: opts.excludeWindows ?? [],
    fit_absorption: opts.fitAbsorption ?? true,
    weights: opts.weights === undefined ? "poisson" : opts.weights,
  });
}

export interface EdsPeakfitElement {
  symbol: string;
  line: string;
  energy_kev: number;
  net_area: number;
  net_area_error: number;
  curve: number[] | null;
}

export interface EdsPeakfitQuant {
  elements: string[];
  atomic_percent: number[];
  weight_percent: number[];
  /** 1σ on at%/wt% from the peak-amplitude fit covariance (pct points). */
  atomic_percent_error: number[];
  weight_percent_error: number[];
}

/** One predicted escape/sum artifact marker (#8). `status` says how it
 *  was handled: freely fitted, modeled as fraction × parent (escape on a
 *  real line), or skipped (blocked sum peak — beware). */
export interface EdsArtifactMark {
  name: string;
  label: string;
  kind: "escape" | "sum";
  energy_kev: number;
  status: "measured" | "modeled" | "skipped";
  area: number | null;
  area_error: number | null;
}

export interface EdsPeakfitResult {
  energy: number[];
  spectrum: number[];
  model: number[];
  elements: EdsPeakfitElement[];
  reduced_chi2: number;
  success: boolean;
  quant?: EdsPeakfitQuant;
  artifacts?: EdsArtifactMark[];
}

/** Constrained multi-Gaussian deconvolution of overlapping EDS peaks;
 *  optional Cliff-Lorimer quant of the deconvolved net areas (#5). */
export function edsPeakfit(
  id: string,
  elements: string[],
  opts: {
    beamKv?: number;
    background?: "none" | "linear" | "bremsstrahlung";
    e0Kev?: number;
    centerTolKev?: number;
    quantify?: boolean;
    kFactors?: number[];
    weights?: "poisson" | null;
    removeArtifacts?: boolean;
    escapeFraction?: number;
  } = {},
): Promise<EdsPeakfitResult> {
  return post("/api/eds/peakfit", {
    image_id: id,
    elements,
    beam_kv: opts.beamKv ?? 200,
    background: opts.background ?? "linear",
    e0_kev: opts.e0Kev ?? null,
    center_tol_kev: opts.centerTolKev ?? 0,
    quantify: opts.quantify ?? false,
    k_factors: opts.kFactors ?? null,
    weights: opts.weights === undefined ? "poisson" : opts.weights,
    remove_artifacts: opts.removeArtifacts ?? false,
    escape_fraction: opts.escapeFraction ?? 0.01,
  });
}

// ── EDS ζ-factor quant + artifact handling (PLAN_SPECTRAL_QUANT #7/#8) ──

export interface EdsZetaQuant extends EdsPeakfitQuant {
  mass_thickness_kg_m2: number;
  mass_thickness_error_kg_m2: number;
  mass_thickness_ug_cm2: number;
  thickness_nm: number | null;
  absorption_factors: number[];
  zeta_factors: number[];
  dose_electrons: number;
}

export interface EdsZetaResult extends Omit<EdsPeakfitResult, "quant"> {
  quant: EdsZetaQuant;
}

/** ζ-factor (Watanabe) quantification (#7): peak deconvolution, then
 *  C_i·ρt = ζ_i·I_i/D_e → composition AND mass-thickness, with a
 *  self-consistent thin-film absorption correction. Supply per-element
 *  `zetaFactors` (kg/m²) or one absolute `zetaSi` to scale the built-in
 *  200 kV k-factor table. */
export function edsZeta(
  id: string,
  elements: string[],
  opts: {
    beamKv?: number;
    background?: "none" | "linear" | "bremsstrahlung";
    e0Kev?: number;
    weights?: "poisson" | null;
    zetaFactors?: number[];
    zetaSi?: number;
    probeCurrentNa?: number;
    liveTimeS?: number;
    takeOffAngleDeg?: number;
    absorption?: boolean;
    densityGCm3?: number;
    removeArtifacts?: boolean;
    escapeFraction?: number;
  } = {},
): Promise<EdsZetaResult> {
  return post("/api/eds/zeta", {
    image_id: id,
    elements,
    beam_kv: opts.beamKv ?? 200,
    background: opts.background ?? "linear",
    e0_kev: opts.e0Kev ?? null,
    weights: opts.weights === undefined ? "poisson" : opts.weights,
    zeta_factors: opts.zetaFactors ?? null,
    zeta_si: opts.zetaSi ?? null,
    probe_current_na: opts.probeCurrentNa ?? 1,
    live_time_s: opts.liveTimeS ?? 100,
    take_off_angle_deg: opts.takeOffAngleDeg ?? 20,
    absorption: opts.absorption ?? true,
    density_g_cm3: opts.densityGCm3 ?? null,
    remove_artifacts: opts.removeArtifacts ?? false,
    escape_fraction: opts.escapeFraction ?? 0.01,
  });
}

export interface EdsArtifactsResult {
  energy: number[];
  spectrum: number[];
  artifacts: EdsArtifactMark[];
  corrected: number[];
}

/** Detect + measure escape/sum/pile-up peaks for spectrum markers (#8). */
export function edsArtifacts(
  id: string,
  elements: string[],
  opts: {
    beamKv?: number;
    background?: "none" | "linear" | "bremsstrahlung";
    e0Kev?: number;
    weights?: "poisson" | null;
    escapeFraction?: number;
  } = {},
): Promise<EdsArtifactsResult> {
  return post("/api/eds/artifacts", {
    image_id: id,
    elements,
    beam_kv: opts.beamKv ?? 200,
    background: opts.background ?? "linear",
    e0_kev: opts.e0Kev ?? null,
    weights: opts.weights === undefined ? "poisson" : opts.weights,
    escape_fraction: opts.escapeFraction ?? 0.01,
  });
}

export interface EdsRecalibrateResult {
  gain: number;
  offset: number;
  anchors: [number, number][]; // [observed_keV, true_keV] pairs used
  skipped: string[];
  applied: boolean;
  scale?: number;
  origin?: number;
  units?: string;
  image?: ImageMeta;
}

/** Linear energy-axis recalibration from known lines (#9). Anchors are
 *  element symbols (true line energy looked up, observed peak auto-located)
 *  and/or explicit [observed, true] keV pairs. Applies the correction to
 *  the image's energy AxisCal when `apply` (default true). */
export function edsRecalibrate(
  id: string,
  opts: {
    elements?: string[];
    pairs?: [number, number][];
    beamKv?: number;
    searchKev?: number;
    apply?: boolean;
  } = {},
): Promise<EdsRecalibrateResult> {
  return post("/api/eds/recalibrate", {
    image_id: id,
    elements: opts.elements ?? [],
    pairs: opts.pairs ?? [],
    beam_kv: opts.beamKv ?? 200,
    search_kev: opts.searchKev ?? 0.15,
    apply: opts.apply ?? true,
  });
}

// ── EDS SI explorer ─────────────────────────────────────────────────

export interface EdsLineEnergyResult {
  symbol: string;
  line: "K" | "L" | "M";
  energy_kev: number;
}

/** Snap the energy window to an element's principal X-ray line. */
export async function edsLineEnergy(
  symbol: string,
  beamKv?: number,
): Promise<EdsLineEnergyResult> {
  const q = beamKv != null ? `?beam_kv=${beamKv}` : "";
  return json(
    await fetch(`/api/eds/line-energy/${encodeURIComponent(symbol)}${q}`),
  );
}

export interface EdsElementMapResult {
  map: number[][]; // H×W float, row-major
  shape: [number, number];
  e_lo: number;
  e_hi: number;
  bg: string;
  total_counts: number;
  map_meta: ImageMeta | null;
}

/** Energy-window integration map for live SI exploration.
 *  bg="linear" subtracts a two-sided background (MATLAB elementMap.m).
 *  saveDerived=true also registers the map as a derived library image. */
export function edsElementMap(
  id: string,
  eLo: number,
  eHi: number,
  opts: {
    bg?: "linear" | "none" | "bremsstrahlung";
    bgWidth?: number;
    bgGap?: number;
    e0Kev?: number; // beam energy (keV) — required for bg="bremsstrahlung"
    saveDerived?: boolean;
  } = {},
): Promise<EdsElementMapResult> {
  return post("/api/eds/element-map", {
    image_id: id,
    e_lo: eLo,
    e_hi: eHi,
    bg: opts.bg ?? "linear",
    bg_width: opts.bgWidth ?? NaN,
    bg_gap: opts.bgGap ?? 0,
    e0_kev: opts.e0Kev ?? NaN,
    save_derived: opts.saveDerived ?? false,
  });
}

export interface EdsLine {
  symbol: string;
  line: string; // "K" | "L" | "M"
  energy_kev: number;
}

/** Characteristic K/L/M lines within [eLo, eHi] keV, optionally filtered to
 *  specific element symbols. Drives the spectrum's peak labels. */
export async function edsLines(
  eLo: number,
  eHi: number,
  symbols?: string[],
): Promise<EdsLine[]> {
  const params = new URLSearchParams({ e_lo: String(eLo), e_hi: String(eHi) });
  if (symbols && symbols.length) params.set("symbols", symbols.join(","));
  const data = await json<{ lines: EdsLine[] }>(
    await fetch(`/api/eds/lines?${params.toString()}`),
  );
  return data.lines;
}
