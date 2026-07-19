import { create } from "zustand";

export const STRUCTURE_MODES = [
  "Atoms",
  "Particles",
  "Grains",
  "Template",
  "GPA",
  "CTF",
  "Lattice",
  "Stitch",
] as const;

export type StructureMode = (typeof STRUCTURE_MODES)[number];

interface WorkshopState {
  structureMode: StructureMode;
  setStructureMode: (mode: StructureMode) => void;
}

/**
 * Navigation intent for the multi-mode Structure workshop.
 *
 * This lives outside the already-large viewer store. Menu commands can select
 * the destination mode before opening the lazy workshop, while ordinary
 * Window > Structure Workshop usage remembers the last mode.
 */
export const useWorkshop = create<WorkshopState>((set) => ({
  structureMode: "Atoms",
  setStructureMode: (structureMode) => set({ structureMode }),
}));
