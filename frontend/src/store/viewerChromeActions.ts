// Appearance + chrome action slice for the viewer store — split from
// viewer.ts (W4 #22, same pass that extracted viewerCloseImage.ts) to bring
// that module back under the 500-line ceiling. Verbatim action bodies;
// viewerState.ts owns the ViewerState contract they implement.
//
// Everything here is a user preference about how the shell LOOKS (theme,
// accent, density) or which panels/overlays are showing — none of it touches
// image data, which is why it factors out cleanly.

import type { StateCreator } from "zustand";

import { pref, systemTheme, THEME_KEY, writePref } from "./viewerSession";
import type { ViewerState } from "./viewerState";
import type { Theme } from "./viewerTypes";

type Set = Parameters<StateCreator<ViewerState>>[0];
type Get = Parameters<StateCreator<ViewerState>>[1];

export function createChromeActions(
  set: Set,
  get: Get,
): Pick<
  ViewerState,
  | "setTheme"
  | "toggleTheme"
  | "setAccent"
  | "setDensity"
  | "toggleLeft"
  | "toggleRight"
  | "toggleMinimap"
  | "toggleColorbar"
  | "setColorbarSide"
  | "toggleScaleBar"
  | "setScaleBarVisible"
  | "setCmdk"
  | "setShorts"
  | "setRadial"
> {
  return {
    setTheme: (choice) => {
      const eff: Theme = choice === "system" ? systemTheme() : choice;
      document.documentElement.setAttribute("data-theme", eff);
      localStorage.setItem(THEME_KEY, choice); // remember the CHOICE, incl. "system"
      writePref("theme", choice);
      set({ theme: eff });
    },

    toggleTheme: () => {
      // quick flip → an explicit dark/light choice (overrides "system")
      get().setTheme(get().theme === "dark" ? "light" : "dark");
    },

    setAccent: (accent) => {
      // accent is a tint: only --accent* (+ capture under amber) change, live
      document.documentElement.setAttribute("data-accent", accent);
      writePref("accent", accent);
      set({ accent });
    },

    setDensity: (density) => {
      document.documentElement.setAttribute("data-density", density);
      writePref("density", density);
      set({ density });
    },

    toggleLeft: () => set((s) => ({ leftCol: !s.leftCol })),
    toggleRight: () => set((s) => ({ rightCol: !s.rightCol })),
    toggleMinimap: () => set((s) => ({ minimap: !s.minimap })),
    toggleColorbar: () => set((s) => ({ colorbar: !s.colorbar })),
    setColorbarSide: (side) => {
      writePref("colorbarSide", side);
      set({ colorbarSide: side });
    },
    toggleScaleBar: () =>
      set((s) => {
        const scaleBarVisible = !s.scaleBarVisible;
        writePref("scaleBarVisible", scaleBarVisible);
        return { scaleBarVisible };
      }),
    setScaleBarVisible: (on) => {
      writePref("scaleBarVisible", on);
      set({ scaleBarVisible: on });
    },
    setCmdk: (cmdk) => set({ cmdk }),
    setShorts: (shorts) => set({ shorts }),
    setRadial: (radial) => set({ radial }),
  };
}

/** Initial values of the chrome preferences, applied to <html> as they are
 *  read so the first paint already carries the user's theme/accent/density
 *  instead of flashing the defaults. Kept beside the setters that maintain
 *  them. */
export function initialChrome(): Pick<
  ViewerState,
  "accent" | "density" | "minimap" | "colorbar" | "colorbarSide" | "scaleBarVisible"
> {
  const accent = pref<ViewerState["accent"]>("accent", "violet");
  document.documentElement.setAttribute("data-accent", accent);
  const density = pref<ViewerState["density"]>("density", "regular");
  document.documentElement.setAttribute("data-density", density);
  return {
    accent,
    density,
    minimap: pref("minimap", true),
    colorbar: pref("colorbarOnByDefault", false),
    colorbarSide: pref<ViewerState["colorbarSide"]>("colorbarSide", "right"),
    scaleBarVisible: pref("scaleBarVisible", true),
  };
}
