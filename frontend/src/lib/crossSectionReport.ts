import type { ImageMeta } from "./api";
import type {
  CrossSectionGrainsSnapshot,
  CrossSectionLayersSnapshot,
} from "../store/crossSection";

export function buildCrossSectionReport(
  image: ImageMeta,
  regionLabel: string,
  layers: CrossSectionLayersSnapshot | null,
  grains: CrossSectionGrainsSnapshot | null,
  exported = new Date().toISOString(),
) {
  return {
    provenance: {
      application: "fermiviewer",
      analysis: "cross-section layers and grains",
      image: image.name,
      image_id: image.id,
      exported,
      pixel_size: image.pixel_size,
      pixel_unit: image.pixel_unit,
      region: regionLabel,
      roi_1_based_inclusive: layers?.roi ?? grains?.roi ?? null,
    },
    layers: layers ? {
      poor_result_acknowledged: layers.qualityAccepted,
      axis: layers.result.axis,
      tilt_deg: layers.result.tilt_deg,
      coherence: layers.result.coherence,
      interfaces: layers.result.interfaces,
      bands: layers.result.layers,
    } : null,
    grains: grains ? {
      poor_result_acknowledged: grains.qualityAccepted,
      method: grains.result.method,
      min_area_px: grains.minArea,
      count: grains.result.n_grains,
      mean_diameter_px: grains.result.mean_diameter_px,
      astm_grain_size: grains.result.astm_grain_size,
      boundary_network_px: grains.result.boundary_network_px,
      triple_junctions: grains.result.n_triple_junctions,
      areas_px: grains.result.areas_px,
      perimeters_px: grains.result.perimeters_px,
      eccentricity: grains.result.eccentricity,
    } : null,
    limitations: [
      "Automatic quality checks are review aids, not scientific validation.",
      "Grain statistics cover the selected region; they are not yet partitioned per detected layer.",
      "Structure-tensor orientation is not equivalent to crystallographic orientation mapping.",
    ],
  };
}
