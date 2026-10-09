// AFM/SPM surface analysis (routes/afm_analysis.py).
import type { ImageMeta } from "./core";
import { post } from "./transport";

export type AfmRoi = [number, number, number, number];
export type AfmLevel = "none" | "plane" | "quadratic";

export const ISO_PARAMS = [
  "Sa", "Sq", "Ssk", "Sku", "Sp", "Sv", "Sz", "Sdq", "Sdr", "Sal", "Str", "Std",
] as const;
export type IsoParam = (typeof ISO_PARAMS)[number];

export interface AfmSurfaceResult {
  params: Record<IsoParam, number | null>;
  units: Record<IsoParam, string>;
  z_unit: string;
  lateral_unit: string;
  n_pixels: number;
  level: AfmLevel;
  roi: AfmRoi | null;
  slopes_calibrated: boolean;
  psd: { frequency: number[]; power: number[] };
  height_hist: { height: number[]; percent: number[] };
  slope_hist: { angle: number[]; percent: number[] };
}

export interface StepHeightResult {
  height: number;
  lower_std: number;
  upper_std: number;
  n_lower: number;
  n_upper: number;
  upper_fraction: number;
  unit: string;
  roi: AfmRoi | null;
}

const path = (id: string, tail: string) => `/api/afm/${encodeURIComponent(id)}/${tail}`;

export function afmSurface(
  id: string,
  options: { level?: AfmLevel; roi?: AfmRoi | null } = {},
): Promise<AfmSurfaceResult> {
  return post(path(id, "surface"), {
    level: options.level ?? "plane",
    roi: options.roi ?? null,
  });
}

/** The 2-D PSD (log10) or autocorrelation of the height map, as a new image. */
export function afmMap(
  id: string,
  kind: "psd" | "acf",
  options: { level?: AfmLevel; roi?: AfmRoi | null } = {},
): Promise<ImageMeta> {
  return post(path(id, "map"), {
    kind,
    level: options.level ?? "plane",
    roi: options.roi ?? null,
  });
}

export function afmStepHeight(id: string, roi: AfmRoi | null): Promise<StepHeightResult> {
  return post(path(id, "step-height"), { roi });
}
