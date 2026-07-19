import { create } from "zustand";

import type { Accent, Density, Theme } from "./viewer";

export interface AppearancePreview {
  theme: Theme;
  accent: Accent;
  density: Density;
}

interface AppearancePreviewState {
  value: AppearancePreview | null;
  setPreview: (value: AppearancePreview | null) => void;
}

/** Ephemeral appearance shown by Preferences; never persisted or serialized. */
export const useAppearancePreviewState = create<AppearancePreviewState>((set) => ({
  value: null,
  setPreview: (value) => set({ value }),
}));
