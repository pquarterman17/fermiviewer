// Scribble-paint state for the trained grain-segmentation mode (parity
// item #8). The StructureWorkshop's "Trained" panel drives the controls
// (class, brush, clear, train); the Stage paints strokes into `strokes`
// and ScribbleOverlay renders them. Kept in its own tiny store so the
// per-pointer-move stroke mutation never re-renders unrelated viewer state.

import { create } from "zustand";

/** Per-class scribble colours (1-indexed classId → palette). */
export const SCRIBBLE_COLORS = [
  "#ff5d5d", // 1 red
  "#5db4ff", // 2 blue
  "#5dff8f", // 3 green
  "#ffd35d", // 4 amber
  "#c98cff", // 5 violet
  "#ff9d5d", // 6 orange
  "#5dffe6", // 7 cyan
  "#ff5dd8", // 8 magenta
] as const;

export interface ScribbleStroke {
  classId: number;
  radius: number; // image px
  points: [number, number][]; // image coords
}

interface ScribbleState {
  active: boolean;
  imageId: string | null;
  classId: number;
  numClasses: number;
  brush: number;
  /** class ids painted on boundaries/background → excluded from grains */
  boundary: number[];
  strokes: ScribbleStroke[];
  begin: (imageId: string) => void;
  end: () => void;
  setClass: (c: number) => void;
  setNumClasses: (n: number) => void;
  setBrush: (r: number) => void;
  toggleBoundary: (c: number) => void;
  startStroke: (pt: [number, number]) => void;
  addPoint: (pt: [number, number]) => void;
  clear: () => void;
}

const clampClasses = (n: number) => Math.max(2, Math.min(8, Math.round(n)));

export const useScribble = create<ScribbleState>((set) => ({
  active: false,
  imageId: null,
  classId: 1,
  numClasses: 2,
  brush: 6,
  boundary: [],
  strokes: [],
  begin: (imageId) =>
    set({ active: true, imageId, strokes: [], classId: 1, boundary: [] }),
  end: () => set({ active: false, imageId: null, strokes: [] }),
  setClass: (classId) => set({ classId }),
  setNumClasses: (n) =>
    set((s) => {
      const numClasses = clampClasses(n);
      return {
        numClasses,
        classId: Math.min(s.classId, numClasses),
        boundary: s.boundary.filter((c) => c <= numClasses),
      };
    }),
  setBrush: (brush) => set({ brush: Math.max(1, Math.min(60, Math.round(brush))) }),
  toggleBoundary: (c) =>
    set((s) => ({
      boundary: s.boundary.includes(c)
        ? s.boundary.filter((b) => b !== c)
        : [...s.boundary, c],
    })),
  startStroke: (pt) =>
    set((s) => ({
      strokes: [
        ...s.strokes,
        { classId: s.classId, radius: s.brush, points: [pt] },
      ],
    })),
  addPoint: (pt) =>
    set((s) => {
      if (s.strokes.length === 0) return {};
      const strokes = s.strokes.slice();
      const last = strokes[strokes.length - 1];
      strokes[strokes.length - 1] = { ...last, points: [...last.points, pt] };
      return { strokes };
    }),
  clear: () => set({ strokes: [] }),
}));
