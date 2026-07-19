import type { ImageMeta } from "./api";
import type {
  CrossSectionGrainsSnapshot,
  CrossSectionLayersSnapshot,
  CrossSectionPerLayerSnapshot,
} from "../store/crossSection";

export function buildCrossSectionReport(
  image: ImageMeta,
  regionLabel: string,
  layers: CrossSectionLayersSnapshot | null,
  grains: CrossSectionGrainsSnapshot | null,
  perLayer: CrossSectionPerLayerSnapshot | null,
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
    per_layer_grains: perLayer ? {
      selected_layer_indices: perLayer.selectedLayerIndices,
      axis: perLayer.result.axis,
      pixel_size: perLayer.result.pixel_size,
      unit: perLayer.result.unit,
      assignment_image_id: perLayer.result.assignment.id,
      layers: perLayer.result.layers,
      limitations: perLayer.result.limitations,
    } : null,
    limitations: [
      "Automatic quality checks are review aids, not scientific validation.",
      ...(perLayer ? [] : ["No reviewed per-layer grain assignment is included."]),
      "Grains crossing a reviewed interface are clipped and reported in each intersected layer.",
      "Shape angle is morphological and is not crystallographic orientation.",
      "Structure-tensor orientation is not equivalent to crystallographic orientation mapping.",
    ],
  };
}
