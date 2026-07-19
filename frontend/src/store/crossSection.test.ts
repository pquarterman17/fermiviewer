import { afterEach, describe, expect, it } from "vitest";

import type { GrainLayersResult, GrainResult, LayersResult } from "../lib/api";
import {
  acceptCrossSectionGrains,
  replaceCrossSectionGrainsAfterEdit,
  useCrossSection,
} from "./crossSection";

afterEach(() => useCrossSection.getState().clear());

describe("cross-section session", () => {
  it("invalidates spatial assignments when either source analysis changes", () => {
    const assignment = {
      sourceId: "src", roi: null, selectedLayerIndices: [0],
      result: { layers: [] } as unknown as GrainLayersResult,
    };
    useCrossSection.getState().setPerLayer(assignment);
    useCrossSection.getState().setLayers({
      sourceId: "src", regionLabel: "Whole image", roi: null,
      result: {} as LayersResult, qualityAccepted: false,
    });
    expect(useCrossSection.getState().perLayer).toBeNull();

    useCrossSection.getState().setPerLayer(assignment);
    useCrossSection.getState().setGrains({
      sourceId: "src", regionLabel: "Whole image", roi: null, minArea: 25,
      result: {} as GrainResult, qualityAccepted: false,
    });
    expect(useCrossSection.getState().perLayer).toBeNull();
  });

  it("keeps an assignment when only poor-result acceptance changes", () => {
    const assignment = {
      sourceId: "src", roi: null, selectedLayerIndices: [0],
      result: { layers: [] } as unknown as GrainLayersResult,
    };
    useCrossSection.getState().setGrains({
      sourceId: "src", regionLabel: "Whole image", roi: null, minArea: 25,
      result: {} as GrainResult, qualityAccepted: false,
    });
    useCrossSection.getState().setPerLayer(assignment);
    acceptCrossSectionGrains();
    expect(useCrossSection.getState().grains?.qualityAccepted).toBe(true);
    expect(useCrossSection.getState().perLayer).toBe(assignment);
  });

  it("replaces matching edited labels and invalidates the old assignment", () => {
    useCrossSection.getState().setGrains({
      sourceId: "src", regionLabel: "Film", roi: [2, 3, 20, 30], minArea: 25,
      result: {} as GrainResult, qualityAccepted: true,
    });
    useCrossSection.getState().setPerLayer({
      sourceId: "src", roi: [2, 3, 20, 30], selectedLayerIndices: [0],
      result: { layers: [] } as unknown as GrainLayersResult,
    });
    const edited = {
      labels: { meta: { grain_source: "src", grain_roi: "2,3,20,30" } },
    } as unknown as GrainResult;
    replaceCrossSectionGrainsAfterEdit(edited);
    expect(useCrossSection.getState().grains?.result).toBe(edited);
    expect(useCrossSection.getState().grains?.qualityAccepted).toBe(false);
    expect(useCrossSection.getState().perLayer).toBeNull();
  });
});
