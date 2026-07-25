import type { ImageMeta } from "./core";
import { post } from "./transport";

export interface InterfaceWidthResult {
  center: number;
  sigma: number;
  width_10_90: number;
  amplitude: number;
  offset: number;
  r_squared: number;
  x_fit: number[];
  y_fit: number[];
  model: "erf" | "sigmoid";
}

export function finiteProfilePairs(
  x: number[],
  y: (number | null)[],
): { x: number[]; y: number[] } {
  const paired = x
    .map((value, index) => [value, y[index]] as const)
    .filter(
      (pair): pair is readonly [number, number] =>
        Number.isFinite(pair[0]) &&
        pair[1] != null &&
        Number.isFinite(pair[1]),
    );
  return {
    x: paired.map(([value]) => value),
    y: paired.map(([, value]) => value),
  };
}

export function analyzeInterfaceWidth(
  x: number[],
  y: (number | null)[],
  model: "erf" | "sigmoid" = "erf",
): Promise<InterfaceWidthResult> {
  const finite = finiteProfilePairs(x, y);
  return post("/api/analyze/interface-width", {
    x: finite.x,
    y: finite.y,
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

export interface DefectResult {
  intersections: number;
  test_lines: number;
  total_line_length: number;
  density: number;
  density_unit: string;
  pixel_unit: string;
  roi: [number, number, number, number] | null;
  h_rows: number[];
  v_cols: number[];
  enhanced: ImageMeta;
  mask: ImageMeta;
}

export function analyzeDefects(
  id: string,
  opts: {
    direction?: number | null;
    kernelLength?: number;
    gridSpacing?: number;
    roi?: [number, number, number, number] | null;
    foilThickness?: number | null;
  } = {},
): Promise<DefectResult> {
  return post("/api/analyze/defects", {
    image_id: id,
    direction: opts.direction ?? null,
    kernel_length: opts.kernelLength ?? 15,
    grid_spacing: opts.gridSpacing ?? 50,
    roi: opts.roi ?? null,
    foil_thickness: opts.foilThickness ?? null,
  });
}
