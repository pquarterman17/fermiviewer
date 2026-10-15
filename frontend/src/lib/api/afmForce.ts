// AFM force curves (routes/afm_force.py): opened force files, one curve's
// analysis, and force-map images.
import type { ForceMeta, ImageMeta } from "./core";
import { json, post } from "./transport";

export type ForceTip = "sphere" | "cone" | "pyramid" | "flat";

export interface ForceSettings {
  spring_constant?: number | null;
  invols?: number | null;
  tip: ForceTip;
  radius_nm: number;
  half_angle_deg: number;
  poisson: number;
  baseline_from: number;
  baseline_to: number;
  max_indent_nm?: number | null;
  max_force_nn?: number | null;
  fit: boolean;
}

export const DEFAULT_FORCE_SETTINGS: ForceSettings = {
  tip: "sphere",
  radius_nm: 20,
  half_angle_deg: 20,
  poisson: 0.5,
  baseline_from: 0,
  baseline_to: 0.5,
  fit: true,
};

export interface ForceTrace {
  z: number[];
  force: number[];
  separation: number[];
}

export const FORCE_VALUES = [
  "youngs_modulus", "e_r", "contact_z", "max_force", "max_indentation", "snap_in",
  "adhesion", "adhesion_energy", "adhesion_z", "fit_r2", "fit_rms", "fit_points",
  "noise_nm", "contact_slope",
] as const;
export type ForceValue = (typeof FORCE_VALUES)[number];

export interface ForceAnalysis {
  values: Record<ForceValue, number | null>;
  units: Record<ForceValue, string>;
  plot: Partial<Record<"approach" | "retract" | "dwell", ForceTrace>>;
  fit: ForceTrace | null;
  spring_constant: number;
  invols: number | null;
  baseline: { slope: number; offset_nm: number };
  evidence: {
    baseline_range_z: [number, number] | null;
    fit_range_z: [number, number] | null;
    residual: ForceTrace | null;
    residual_lag1: number | null;
    fit_at_bounds: boolean;
    calibration_complete: boolean;
  };
}

export interface ForceMapsResult {
  n: number;
  failed: number;
  accepted: number;
  rejected: number;
  table: Record<ForceMapMetric, (number | null)[]> & { accepted: boolean[] };
  grids: (Record<ForceMapMetric, (number | null)[][]> & { accepted: boolean[][] }) | null;
  summaries: Record<ForceMapMetric, {
    n: number; median: number | null; mad: number | null; q05: number | null; q95: number | null;
  }>;
  units: Record<string, string>;
  images: ImageMeta[];
}

export type ForceMapMetric = "youngs_modulus" | "adhesion" | "contact_z" | "max_force" |
  "fit_r2" | "fit_rms" | "fit_points" | "residual_lag1";

const base = (id: string) => `/api/afm/force/${encodeURIComponent(id)}`;

export async function listForceFiles(): Promise<ForceMeta[]> {
  return json(await fetch("/api/afm/force"));
}

export async function closeForceFile(id: string): Promise<void> {
  await json(await fetch(base(id), { method: "DELETE" }));
}

export function analyzeForceCurve(
  id: string,
  index: number,
  settings: ForceSettings,
): Promise<ForceAnalysis> {
  return post(`${base(id)}/curve/${index}/analyze`, settings);
}

export function forceMaps(id: string, settings: ForceSettings): Promise<ForceMapsResult> {
  return post(`${base(id)}/maps`, settings);
}

export function startForceMapsJob(
  id: string, settings: ForceSettings,
): Promise<{ job_id: string }> {
  return post(`${base(id)}/maps`, { ...settings, run_async: true });
}
