import type { ImageMeta } from "./core";
import { post } from "./transport";

export interface InterfaceWidthResult {
  center: number;
  sigma: number;
  width_10_90: number;
  r_squared: number;
}

export function analyzeInterfaceWidth(
  x: number[],
  y: (number | null)[],
  model: "erf" | "sigmoid" = "erf",
): Promise<InterfaceWidthResult> {
  return post("/api/analyze/interface-width", {
    x,
    y: y.map((value) => value ?? 0),
    model,
  });
}

export interface NoiseResult {
  sigma: number;
  snr_db: number | null;
  snr_linear: number | null;
  noise_type: string;
  method: "mad" | "localvar" | "both";
  recommendation: string;
  roi: [number, number, number, number] | null;
  n_pixels: number;
  block_size: number;
  n_blocks: number;
  block_means: number[];
  block_variances: number[];
  regression_slope: number | null;
  regression_intercept: number | null;
  regression_r_squared: number | null;
}

export function analyzeNoise(
  id: string,
  opts: {
    method?: NoiseResult["method"];
    roi?: [number, number, number, number] | null;
  } = {},
): Promise<NoiseResult> {
  return post("/api/analyze/noise", {
    image_id: id,
    method: opts.method ?? "mad",
    roi: opts.roi ?? null,
  });
}

export function analyzeDefects(id: string): Promise<{
  intersections: number;
  test_lines: number;
  density: number;
  density_unit: string;
  enhanced: ImageMeta;
}> {
  return post("/api/analyze/defects", { image_id: id });
}
