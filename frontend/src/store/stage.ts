// Ephemeral high-frequency stage state (cursor, zoom, raw raster, active
// profile). Separate from the main viewer store so 120 Hz pointermove
// only re-renders the chips that subscribe — never the shell.

import { create } from "zustand";

import type { ProfileResult, Raster16 } from "../lib/api";

export interface ActiveProfile extends ProfileResult {
  measureId: string;
}

interface StageInfo {
  cursor: { x: number; y: number } | null;
  zoom: number | null;
  /** Raw raster of the active image — drives the value readout and
   *  lets the Adjust panel map normalized window ↔ real units. */
  raster: Raster16 | null;
  profile: ActiveProfile | null;
  setCursor: (c: { x: number; y: number } | null) => void;
  setZoom: (z: number | null) => void;
  setRaster: (r: Raster16 | null) => void;
  setProfile: (p: ActiveProfile | null) => void;
}

export const useStageInfo = create<StageInfo>((set) => ({
  cursor: null,
  zoom: null,
  raster: null,
  profile: null,
  setCursor: (cursor) => set({ cursor }),
  setZoom: (zoom) => set({ zoom }),
  setRaster: (raster) => set({ raster }),
  setProfile: (profile) => set({ profile }),
}));

/** Real intensity at integer pixel (x, y), or null when out of range. */
export function rasterValue(
  r: Raster16 | null,
  x: number,
  y: number,
): number | null {
  if (!r) return null;
  const xi = Math.floor(x);
  const yi = Math.floor(y);
  if (xi < 0 || yi < 0 || xi >= r.w || yi >= r.h) return null;
  return (r.data[yi * r.w + xi] / 65535) * (r.vmax - r.vmin) + r.vmin;
}
