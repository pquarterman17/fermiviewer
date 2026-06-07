// Ephemeral high-frequency stage readouts (cursor px, zoom). Separate
// from the main viewer store so 120 Hz pointermove only re-renders the
// chips that subscribe (Readout, ZoomChip, StatusBar) — never the shell.

import { create } from "zustand";

interface StageInfo {
  cursor: { x: number; y: number } | null;
  zoom: number | null;
  setCursor: (c: { x: number; y: number } | null) => void;
  setZoom: (z: number | null) => void;
}

export const useStageInfo = create<StageInfo>((set) => ({
  cursor: null,
  zoom: null,
  setCursor: (cursor) => set({ cursor }),
  setZoom: (zoom) => set({ zoom }),
}));
