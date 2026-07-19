import { create } from "zustand";

import type { GrainLayersResult, GrainResult, LayersResult } from "../lib/api";
import type { AnalysisRoi } from "../hooks/useAnalysisRoi";

export interface CrossSectionLayersSnapshot {
  sourceId: string;
  regionLabel: string;
  roi: AnalysisRoi | null;
  result: LayersResult;
  qualityAccepted: boolean;
}

export interface CrossSectionGrainsSnapshot {
  sourceId: string;
  regionLabel: string;
  roi: AnalysisRoi | null;
  minArea: number;
  result: GrainResult;
  qualityAccepted: boolean;
}

export interface CrossSectionPerLayerSnapshot {
  sourceId: string;
  roi: AnalysisRoi | null;
  selectedLayerIndices: number[];
  result: GrainLayersResult;
}

interface CrossSectionState {
  layers: CrossSectionLayersSnapshot | null;
  grains: CrossSectionGrainsSnapshot | null;
  perLayer: CrossSectionPerLayerSnapshot | null;
  setLayers: (value: CrossSectionLayersSnapshot) => void;
  setGrains: (value: CrossSectionGrainsSnapshot) => void;
  setPerLayer: (value: CrossSectionPerLayerSnapshot) => void;
  clear: () => void;
}

export const useCrossSection = create<CrossSectionState>((set) => ({
  layers: null,
  grains: null,
  perLayer: null,
  setLayers: (layers) => set({ layers, perLayer: null }),
  setGrains: (grains) => set({ grains, perLayer: null }),
  setPerLayer: (perLayer) => set({ perLayer }),
  clear: () => set({ layers: null, grains: null, perLayer: null }),
}));

export function matchesCrossSectionRegion(
  snapshot: { sourceId: string; roi: AnalysisRoi | null } | null,
  sourceId: string | null,
  roi: AnalysisRoi | null,
): boolean {
  return snapshot?.sourceId === sourceId
    && snapshot?.roi?.join(":") === roi?.join(":")
    && Boolean(snapshot?.roi) === Boolean(roi);
}

export function recordCrossSectionGrains(
  sourceId: string,
  regionLabel: string,
  roi: AnalysisRoi | null,
  minArea: number,
  result: GrainResult,
): void {
  useCrossSection.getState().setGrains({
    sourceId, regionLabel, roi, minArea, result, qualityAccepted: false,
  });
}

export function acceptCrossSectionLayers(): void {
  const current = useCrossSection.getState().layers;
  if (current) useCrossSection.setState({ layers: { ...current, qualityAccepted: true } });
}

export function acceptCrossSectionGrains(): void {
  const current = useCrossSection.getState().grains;
  if (current) useCrossSection.setState({ grains: { ...current, qualityAccepted: true } });
}

export function replaceCrossSectionGrainsAfterEdit(result: GrainResult): void {
  const current = useCrossSection.getState().grains;
  if (!current || result.labels.meta?.["grain_source"] !== current.sourceId) return;
  const resultRoi = typeof result.labels.meta?.["grain_roi"] === "string"
    ? result.labels.meta["grain_roi"] : null;
  if (resultRoi !== (current.roi?.join(",") ?? null)) return;
  useCrossSection.getState().setGrains({ ...current, result, qualityAccepted: false });
}
