import type { AnalysisRoi } from "../hooks/useAnalysisRoi";
import type { GrainMethod, GrainParams, GrainResult, ImageMeta } from "./api";

/** Follow an editable grain-label image back to its original raster. */
export function grainSourceId(
  id: string,
  images: Record<string, ImageMeta>,
): string {
  const source = images[id]?.meta?.["grain_source"];
  return typeof source === "string" && images[source] ? source : id;
}

/** The out-of-range message for a method's tuning knob, in the words the
 *  workshop shows ("coarseness", "merge thr", "classes"), or null when the
 *  values are acceptable. Without it the server's validation error named
 *  the wire field ("granularity: Input should be less than or equal to 1"),
 *  which appears nowhere in the UI. Bounds mirror routes/structure_grains.py. */
export function grainParamError(
  method: Exclude<GrainMethod, "trained">,
  knob: string,
  denoise: string,
): string | null {
  const v = Number(knob);
  const [label, lo, hi] =
    method === "kmeans"
      ? ["classes", 2, 10]
      : method === "rag"
        ? ["merge threshold", 0, 1]
        : ["coarseness", 0, 1];
  if (knob.trim() !== "" && (!Number.isFinite(v) || v < lo || v > hi)) {
    return `${label} must be between ${lo} and ${hi}`;
  }
  const d = Number(denoise);
  if (method !== "kmeans" && denoise.trim() !== "" && (!Number.isFinite(d) || d < 0 || d > 10)) {
    return "denoise must be between 0 and 10";
  }
  return null;
}

export function buildClassicGrainParams(
  method: Exclude<GrainMethod, "trained">,
  roi: AnalysisRoi | null,
  knob: string,
  minArea: string,
  denoise: string,
): GrainParams {
  const common = {
    method,
    roi,
    min_area: Number(minArea) || 25,
  };
  if (method === "kmeans") return { ...common, k: Number(knob) || 3 };
  if (method === "rag") {
    return {
      ...common,
      merge_threshold: Number(knob) || 0.08,
      denoise_sigma: Number(denoise) || 0,
    };
  }
  return {
    ...common,
    granularity: Number(knob) || 0.05,
    denoise_sigma: Number(denoise) || 0,
  };
}

/** The per-grain results table (ResultsWindow) for a segmentation. */
export function grainResultsTable(r: GrainResult, method: string) {
  return {
    title: `Grains (${r.n_grains}) · ${method}`,
    columns: ["#", "area (px)", "perim (px)", "ecc."],
    rows: r.areas_px.map((a, i) => [
      i + 1,
      Math.round(a),
      Math.round(r.perimeters_px[i] ?? 0),
      (r.eccentricity[i] ?? 0).toFixed(2),
    ]),
  };
}
