import { describe, expect, it } from "vitest";

import type { GrainLayersResult, GrainResult, ImageMeta, LayersResult } from "./api";
import { buildCrossSectionReport } from "./crossSectionReport";

const image = {
  id: "src", name: "film.dm4", kind: "image", shape: [100, 200],
  pixel_size: 0.5, pixel_unit: "nm",
} as ImageMeta;
const layers = {
  axis: "y", tilt_deg: 1.2, coherence: 0.8, interfaces: [], layers: [],
} as unknown as LayersResult;
const grains = {
  method: "gradient", n_grains: 12, mean_diameter_px: 8,
  astm_grain_size: null, boundary_network_px: 40, n_triple_junctions: 3,
  areas_px: [10], perimeters_px: [5], eccentricity: [0.2],
} as GrainResult;

describe("cross-section report", () => {
  it("combines provenance, layer, and grain results without dropping arrays", () => {
    const report = buildCrossSectionReport(
      image,
      "Film only",
      { sourceId: "src", regionLabel: "Film only", roi: [2, 3, 90, 180], result: layers, qualityAccepted: true },
      { sourceId: "src", regionLabel: "Film only", roi: [2, 3, 90, 180], minArea: 25, result: grains, qualityAccepted: false },
      {
        sourceId: "src", roi: [2, 3, 90, 180], selectedLayerIndices: [1],
        result: {
          axis: "y", pixel_size: 0.5, unit: "nm", layers: [{ index: 1 }],
          assignment: { id: "assignment" }, limitations: ["shape only"],
        } as GrainLayersResult,
      },
      "2026-07-19T12:00:00Z",
    );
    expect(report.provenance).toMatchObject({
      image: "film.dm4",
      exported: "2026-07-19T12:00:00Z",
      roi_1_based_inclusive: [2, 3, 90, 180],
    });
    expect(report.grains?.areas_px).toEqual([10]);
    expect(report.layers?.axis).toBe("y");
    expect(report.layers?.poor_result_acknowledged).toBe(true);
    expect(report.per_layer_grains?.selected_layer_indices).toEqual([1]);
    expect(report.per_layer_grains?.layers).toEqual([{ index: 1 }]);
    expect(report.limitations).not.toContain("No reviewed per-layer grain assignment is included.");
  });
});
