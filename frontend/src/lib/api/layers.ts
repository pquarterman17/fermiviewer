// Extracted from lib/api.ts; public imports remain stable via the barrel.
import { post } from "./transport";

// ── Cross-section layers (PLAN_CROSS_SECTION_LAYERS) ─────────────────

export interface InterfaceRoughness {
  sigma_ci: [number, number] | null;  // 95% block-bootstrap CI on sigma_w
  sigma_raw: number | null;           // robust rms before noise subtraction
  noise_floor: number | null;         // edge-localisation jitter estimate
  quality: number;                    // fraction of columns kept (0..1)
  xi: number | null;                  // HHCF correlation length, calibrated
  hurst: number | null;               // HHCF Hurst exponent
  sigma_chem: number | null;          // sqrt(sigma_erf² − sigma_w²), or null
  psd_wavelength: number[];           // lateral wavelength per PSD bin
  psd_power: number[];
}

export interface LayerInterface {
  position: number;          // sub-pixel depth (profile pixels)
  sigma_erf: number | null;  // erf transition width, calibrated units
  r_squared: number;
  sigma_w: number | null;    // geometric waviness, calibrated (Tier 2)
  trace: number[] | null;    // per-column edge depths (px)
  roughness: InterfaceRoughness | null;  // full metrology (waviness on)
}

export interface LayerBand {
  index: number;
  top: number;
  bottom: number;
  thickness: number;         // calibrated units
  thickness_std: number | null;  // FOV thickness std, calibrated (Tier 2)
  conformality: number | null;   // Pearson r between the bounding traces
}

export interface LayersResult {
  axis: "y" | "x";
  layers_horizontal: boolean;
  tilt_deg: number | null;
  coherence: number | null;
  pixel_size: number;
  unit: string;
  depth_pos: number[];
  depth_profile: number[];
  interfaces: LayerInterface[];
  layers: LayerBand[];
}

/** Cross-section layer analysis: thickness + interface sharpness (σ_erf). */
export function analyzeLayers(
  id: string,
  opts: {
    roi?: [number, number, number, number] | null;
    axis?: "auto" | "y" | "x";
    sensitivity?: number;
    nLayers?: number;
    reduce?: "mean" | "sum" | "median";
    fitWindow?: number;
    waviness?: boolean;
    traceWindow?: number;
    modality?: "haadf" | "eels" | "bf" | "df";
    destripe?: boolean;
  } = {},
): Promise<LayersResult> {
  return post("/api/analyze/layers", {
    image_id: id,
    roi: opts.roi ?? null,
    axis: opts.axis ?? "auto",
    sensitivity: opts.sensitivity ?? 0.3,
    n_layers: opts.nLayers ?? 0,
    reduce: opts.reduce ?? "mean",
    fit_window: opts.fitWindow ?? 15,
    waviness: opts.waviness ?? false,
    trace_window: opts.traceWindow ?? 10,
    modality: opts.modality ?? "haadf",
    destripe: opts.destripe ?? false,
  });
}

export interface LayersMultiMap {
  image_id: string;
  name: string;
  interfaces: { position: number; sigma_erf: number | null; sigma_w: number | null }[];
  layers: { index: number; thickness: number; thickness_std: number | null }[];
}

export interface LayersMultiResult {
  axis: "y" | "x";
  unit: string;
  reference_positions: number[];
  maps: LayersMultiMap[];
}

/** Per-element interface roughness across several maps (EELS/EDS · #7).
 *  Detects interfaces on the reference map, re-measures them on each. */
export function analyzeLayersMulti(
  imageIds: string[],
  opts: { reference?: number; modality?: "haadf" | "eels" | "bf" | "df"; waviness?: boolean } = {},
): Promise<LayersMultiResult> {
  return post("/api/analyze/layers/multi", {
    image_ids: imageIds,
    reference: opts.reference ?? 0,
    modality: opts.modality ?? "haadf",
    waviness: opts.waviness ?? true,
  });
}

/** Re-measure layers from a user-edited interface list (Tier 3 #6). */
export function editLayers(
  id: string,
  positions: number[],
  opts: {
    roi?: [number, number, number, number] | null;
    axis?: "y" | "x";
    waviness?: boolean;
    reduce?: "mean" | "sum" | "median";
    destripe?: boolean;
  } = {},
): Promise<LayersResult> {
  return post("/api/analyze/layers/edit", {
    image_id: id,
    positions,
    roi: opts.roi ?? null,
    axis: opts.axis ?? "y",
    waviness: opts.waviness ?? false,
    reduce: opts.reduce ?? "mean",
    destripe: opts.destripe ?? false,
  });
}
