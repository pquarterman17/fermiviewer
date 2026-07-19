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

export const STRUCTURE_MODE_DESCRIPTIONS: Record<StructureMode, string> = {
  Atoms: "Atom-column detection, fitting & PPA strain",
  Particles: "Threshold-based particle detection & counting",
  Grains: "Grain segmentation & boundary metrology",
  Template: "Template matching via a drawn ROI motif",
  GPA: "Geometric phase analysis — strain from FFT g-vectors",
  CTF: "Contrast transfer function fit (defocus, R²)",
  Lattice: "Lattice spacing & unit cell from FFT spot picks",
  Stitch: "Stitch multiple tiles into one mosaic",
};

interface WorkshopState {
  structureMode: StructureMode;
  setStructureMode: (mode: StructureMode) => void;
  analysisRegionChoices: Record<string, string>;
  setAnalysisRegionChoice: (imageId: string, choice: string) => void;
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
  analysisRegionChoices: {},
  setAnalysisRegionChoice: (imageId, choice) => set((state) => ({
    analysisRegionChoices: { ...state.analysisRegionChoices, [imageId]: choice },
  })),
}));
