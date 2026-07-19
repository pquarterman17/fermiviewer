import { describe, expect, it } from "vitest";

import type { GrainResult, LayersResult } from "./api";
import { assessGrainQuality, assessLayerQuality } from "./analysisQuality";

function layers(overrides: Partial<LayersResult> = {}): LayersResult {
  return {
    axis: "y", layers_horizontal: true, tilt_deg: 0, coherence: 0.8,
    pixel_size: 1, unit: "px", depth_pos: Array.from({ length: 100 }, (_, i) => i),
    depth_profile: [], interfaces: [
      { position: 30, sigma_erf: 1, r_squared: 0.95, sigma_w: null, trace: null, roughness: null },
      { position: 70, sigma_erf: 1, r_squared: 0.95, sigma_w: null, trace: null, roughness: null },
    ], layers: [], ...overrides,
  };
}

function grains(overrides: Partial<GrainResult> = {}): GrainResult {
  return {
    n_grains: 20, method: "gradient", labels: {} as GrainResult["labels"],
    mean_diameter_px: 20, boundary_length_px: 1, boundary_network_px: 1,
    boundary_length_calibrated: null, n_boundary_segments: 1,
    n_triple_junctions: 5, astm_grain_size: null,
    areas_px: Array(20).fill(1000), perimeters_px: [], eccentricity: [], unit: "px",
    ...overrides,
  };
}

describe("layer quality", () => {
  it("rates a coherent, well-fit result good", () => {
    expect(assessLayerQuality(layers()).rating).toBe("good");
  });
  it("flags missing interfaces and bad fits", () => {
    expect(assessLayerQuality(layers({ coherence: 0.1, interfaces: [] })).rating).toBe("poor");
    expect(assessLayerQuality(layers({ interfaces: [
      { ...layers().interfaces[0], r_squared: 0.3 },
    ] })).rating).toBe("poor");
  });
});

describe("grain quality", () => {
  it("rates a plausible population good", () => {
    expect(assessGrainQuality(grains(), [512, 512], 25, null).rating).toBe("good");
  });
  it("catches the live-audit over-segmentation pattern", () => {
    const result = grains({ n_grains: 1976, areas_px: Array(1976).fill(26) });
    const quality = assessGrainQuality(result, [512, 512], 25, null);
    expect(quality.rating).toBe("poor");
    expect(quality.concerns.map((c) => c.message).join(" ")).toMatch(/megapixel/);
    expect(quality.concerns.map((c) => c.message).join(" ")).toMatch(/cutoff/);
  });
});
