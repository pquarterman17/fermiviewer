import type { AnalysisRoi } from "../hooks/useAnalysisRoi";
import type { GrainMethod, GrainParams, ImageMeta } from "./api";

/** Follow an editable grain-label image back to its original raster. */
export function grainSourceId(
  id: string,
  images: Record<string, ImageMeta>,
): string {
  const source = images[id]?.meta?.["grain_source"];
  return typeof source === "string" && images[source] ? source : id;
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
