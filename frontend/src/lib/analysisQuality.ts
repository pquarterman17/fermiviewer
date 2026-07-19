import type { GrainResult, LayersResult } from "./api";

export type QualityRating = "good" | "review" | "poor";

export interface QualityConcern {
  rating: Exclude<QualityRating, "good">;
  message: string;
  suggestion: string;
}

export interface QualityAssessment {
  rating: QualityRating;
  summary: string;
  concerns: QualityConcern[];
}

function assessment(concerns: QualityConcern[], good: string): QualityAssessment {
  const rating = concerns.some((c) => c.rating === "poor")
    ? "poor"
    : concerns.length ? "review" : "good";
  return {
    rating,
    summary: rating === "good" ? good
      : rating === "poor" ? "Automatic checks found a likely detection failure."
        : "Automatic checks found items that need visual review.",
    concerns,
  };
}

function concern(
  rating: "review" | "poor", message: string, suggestion: string,
): QualityConcern {
  return { rating, message, suggestion };
}

export function assessLayerQuality(
  result: LayersResult,
  expectedLayers = 0,
): QualityAssessment {
  const issues: QualityConcern[] = [];
  const n = result.interfaces.length;
  const length = result.depth_pos.length;
  if (n === 0) {
    issues.push(concern("poor", "No interfaces were detected.",
      "Lower sensitivity, choose the growth axis, or restrict the region."));
  }
  if (result.coherence == null) {
    issues.push(concern("review", "Orientation confidence is unavailable.",
      "Set the growth axis manually and inspect the overlay."));
  } else if (result.coherence < 0.2) {
    issues.push(concern("poor", `Orientation coherence is ${result.coherence.toFixed(2)}.`,
      "Use a tighter film ROI or set the growth axis manually."));
  } else if (result.coherence < 0.45) {
    issues.push(concern("review", `Orientation coherence is only ${result.coherence.toFixed(2)}.`,
      "Confirm the growth axis and interface-line placement."));
  }
  const badFits = result.interfaces.filter((i) => i.r_squared < 0.5).length;
  const weakFits = result.interfaces.filter((i) => i.r_squared >= 0.5 && i.r_squared < 0.8).length;
  if (badFits) issues.push(concern("poor", `${badFits} interface fit(s) have R² below 0.50.`,
    "Adjust sensitivity/fit region and remove unsupported interfaces."));
  else if (weakFits) issues.push(concern("review", `${weakFits} interface fit(s) have R² below 0.80.`,
    "Inspect those interfaces and edit the list if needed."));
  if (length > 0 && n > 0) {
    const margin = Math.max(3, length * 0.03);
    const nearEdge = result.interfaces.filter(
      (i) => i.position < margin || i.position > length - 1 - margin,
    ).length;
    if (nearEdge) issues.push(concern("review", `${nearEdge} interface(s) lie near an ROI edge.`,
      "Expand the region or confirm these are physical outer interfaces."));
    const sorted = result.interfaces.map((i) => i.position).sort((a, b) => a - b);
    const minGap = Math.min(...sorted.slice(1).map((p, i) => p - sorted[i]));
    if (sorted.length > 1 && minGap < Math.max(2, length * 0.01)) {
      issues.push(concern("poor", `Two interfaces are only ${minGap.toFixed(1)} px apart.`,
        "Reduce sensitivity or remove the duplicate interface."));
    }
  }
  if (expectedLayers > 0 && n !== expectedLayers - 1) {
    issues.push(concern("review", `Found ${n} interfaces; ${expectedLayers - 1} were expected.`,
      "Review the layer-count hint and edit the interface list."));
  }
  return assessment(issues, "Automatic checks found no obvious layer-detection problem.");
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

export function assessGrainQuality(
  result: GrainResult,
  imageShape: number[],
  minArea: number,
  roi: [number, number, number, number] | null,
): QualityAssessment {
  const issues: QualityConcern[] = [];
  const h = roi ? roi[2] - roi[0] + 1 : (imageShape[0] ?? 0);
  const w = roi ? roi[3] - roi[1] + 1 : (imageShape[1] ?? 0);
  const analysisArea = Math.max(1, h * w);
  const densityPerMp = result.n_grains * 1_000_000 / analysisArea;
  if (result.n_grains < 2) issues.push(concern("poor", "Fewer than two grains were found.",
    "Choose another method, lower minimum area, or refine the region."));
  if (densityPerMp > 5000) issues.push(concern("poor",
    `Grain density is ${Math.round(densityPerMp).toLocaleString()} per megapixel.`,
    "Increase coarseness/denoise/minimum area and inspect for noise fragments."));
  else if (densityPerMp > 1500) issues.push(concern("review",
    `Grain density is ${Math.round(densityPerMp).toLocaleString()} per megapixel.`,
    "Zoom in and confirm boundaries are not following image noise."));
  if (result.areas_px.length) {
    const cutoff = result.areas_px.filter((a) => a <= minArea * 1.25).length /
      result.areas_px.length;
    if (cutoff >= 0.5) issues.push(concern("poor",
      `${Math.round(cutoff * 100)}% of grains sit at the minimum-area cutoff.`,
      "Increase minimum area or denoise before segmenting."));
    else if (cutoff >= 0.25) issues.push(concern("review",
      `${Math.round(cutoff * 100)}% of grains sit near the minimum-area cutoff.`,
      "Check small components before accepting the result."));
    const med = median(result.areas_px);
    if (med <= minArea * 1.5) issues.push(concern("poor",
      `Median grain area (${med.toFixed(0)} px²) is close to the cutoff.`,
      "Increase coarseness, denoise, or minimum area."));
    const total = result.areas_px.reduce((sum, a) => sum + a, 0);
    const largest = Math.max(...result.areas_px) / Math.max(1, total);
    if (largest > 0.8) issues.push(concern("review",
      `One component contains ${Math.round(largest * 100)}% of labelled area.`,
      "Confirm the method did not classify a whole intensity band as one grain."));
  }
  return assessment(issues, "Automatic checks found no obvious grain-segmentation problem.");
}
