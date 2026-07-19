import { create } from "zustand";

import type { GrainResult, LayersResult } from "../lib/api";
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

interface CrossSectionState {
  layers: CrossSectionLayersSnapshot | null;
  grains: CrossSectionGrainsSnapshot | null;
  setLayers: (value: CrossSectionLayersSnapshot) => void;
  setGrains: (value: CrossSectionGrainsSnapshot) => void;
  clear: () => void;
}

export const useCrossSection = create<CrossSectionState>((set) => ({
  layers: null,
  grains: null,
  setLayers: (layers) => set({ layers }),
  setGrains: (grains) => set({ grains }),
  clear: () => set({ layers: null, grains: null }),
}));

export function matchesCrossSectionRegion(
  snapshot: { sourceId: string; roi: AnalysisRoi | null } | null,
  sourceId: string | null,
  roi: AnalysisRoi | null,
): boolean {
  return snapshot?.sourceId === sourceId
    && snapshot.roi?.join(":") === roi?.join(":")
    && Boolean(snapshot.roi) === Boolean(roi);
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
