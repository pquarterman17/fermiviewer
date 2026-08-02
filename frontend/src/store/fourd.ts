// FourD workshop state (PLAN_4DSTEM #4): the dataset list, which one is
// selected, the probed scan position + its diffraction pattern, and the
// reciprocal-space aperture that drives virtual-detector map generation.
//
// Kept as its own store (like crossSection.ts/scribble.ts) rather than
// folded into viewer.ts: FourD datasets are deliberately NOT ImageMeta (see
// lib/api/core.ts's FourDMeta doc comment) and the pattern raster updates
// on every probe move, which would be a lot of unrelated churn on the
// already-capped viewer store.
//
// Every field here is a primitive, a plain object replaced wholesale on
// write, or an array replaced wholesale on write — never a fresh literal
// minted inside a selector — so selectors stay reference-stable (repo rule:
// a fresh `?? []`/`{}` in a selector is the black-screen bug).

import { create } from "zustand";

import {
  computeVirtualDetector,
  fetchData16,
  fetchFourDMeanPattern,
  fetchFourDNav,
  listFourD,
  type ApertureShape,
  type FourDMeta,
  type ImageMeta,
  type Raster16,
} from "../lib/api";
import { useViewer } from "./viewer";

export type ApertureMode = "bf" | "abf" | "adf" | "custom";

export interface FourDAperture {
  /** null when autoCenter is on — the server centers from the mean pattern. */
  centerKy: number | null;
  centerKx: number | null;
  innerR: number;
  outerR: number;
  shape: ApertureShape;
  mode: ApertureMode;
  autoCenter: boolean;
}

export interface FourDProbe {
  y: number;
  x: number;
}

/** BF/ABF/ADF radii as a fraction of `min(det_shape)` — conventional STEM
 *  detector geometry (BF disk near the direct beam; ADF annulus well
 *  outside it; ABF annulus just inside the BF disk edge). "custom" is a
 *  pass-through: switching to it does not move the current radii, it just
 *  stops a manual edit from being silently overwritten by a preset. */
export function apertureRadiiForMode(
  mode: ApertureMode,
  detShape: readonly [number, number],
  current?: { innerR: number; outerR: number; shape: ApertureShape },
): { innerR: number; outerR: number; shape: ApertureShape } {
  const size = Math.min(detShape[0], detShape[1]);
  switch (mode) {
    case "bf":
      return { innerR: 0, outerR: size / 8, shape: "circle" };
    case "abf":
      return { innerR: size / 16, outerR: size / 8, shape: "annulus" };
    case "adf":
      return { innerR: size / 6, outerR: size / 2.5, shape: "annulus" };
    case "custom":
      return current ?? { innerR: size / 16, outerR: size / 8, shape: "annulus" };
  }
}

function defaultAperture(detShape: readonly [number, number]): FourDAperture {
  return {
    centerKy: null,
    centerKx: null,
    autoCenter: true,
    mode: "bf",
    ...apertureRadiiForMode("bf", detShape),
  };
}

interface FourDState {
  datasets: FourDMeta[];
  selectedId: string | null;
  navMeta: ImageMeta | null;
  navRaster: Raster16 | null;
  probe: FourDProbe | null;
  patternRaster: Raster16 | null;
  aperture: FourDAperture;
  busyList: boolean;
  busyNav: boolean;
  busyPattern: boolean;
  busyCompute: boolean;
  status: string | null;

  fetchDatasets: () => Promise<void>;
  selectDataset: (id: string) => Promise<void>;
  fetchNavRaster: () => Promise<void>;
  showNavImage: () => Promise<void>;
  setProbe: (probe: FourDProbe | null) => void;
  setPatternRaster: (raster: Raster16 | null) => void;
  fetchMeanPattern: () => Promise<void>;
  setStatus: (status: string | null) => void;
  setBusyPattern: (busy: boolean) => void;
  setApertureMode: (mode: ApertureMode) => void;
  setApertureField: (
    patch: Partial<Pick<FourDAperture, "centerKy" | "centerKx" | "innerR" | "outerR" | "shape">>,
  ) => void;
  setAutoCenter: (autoCenter: boolean) => void;
  computeMap: () => Promise<void>;
  reset: () => void;
}

const initial = {
  datasets: [] as FourDMeta[],
  selectedId: null as string | null,
  navMeta: null as ImageMeta | null,
  navRaster: null as Raster16 | null,
  probe: null as FourDProbe | null,
  patternRaster: null as Raster16 | null,
  aperture: defaultAperture([256, 256]),
  busyList: false,
  busyNav: false,
  busyPattern: false,
  busyCompute: false,
  status: null as string | null,
};

function detShapeOf(datasets: FourDMeta[], id: string | null): [number, number] {
  const ds = datasets.find((d) => d.id === id);
  return ds ? [ds.det_shape[0], ds.det_shape[1]] : [256, 256];
}

export const useFourD = create<FourDState>((set, get) => ({
  ...initial,

  fetchDatasets: async () => {
    set({ busyList: true });
    try {
      const datasets = await listFourD();
      set({ datasets, status: null });
    } catch (e) {
      set({ status: `4D datasets: ${(e as Error).message}` });
    } finally {
      set({ busyList: false });
    }
  },

  selectDataset: async (id) => {
    const detShape = detShapeOf(get().datasets, id);
    set({
      selectedId: id,
      navMeta: null,
      navRaster: null,
      probe: null,
      patternRaster: null,
      aperture: defaultAperture(detShape),
      status: null,
    });
    // Populate the mean pattern + nav minimap eagerly (both are needed by
    // this workshop's own panels) WITHOUT touching the main viewer store —
    // that only happens when the user explicitly clicks "Show nav image"
    // (see showNavImage below), so merely browsing the dataset picker never
    // hijacks the main Stage's active image.
    await Promise.all([get().fetchMeanPattern(), get().fetchNavRaster()]);
  },

  fetchNavRaster: async () => {
    const id = get().selectedId;
    if (!id) return;
    set({ busyNav: true });
    try {
      const meta = await fetchFourDNav(id);
      const navRaster = await fetchData16(meta.id);
      set({ navMeta: meta, navRaster, status: null });
    } catch (e) {
      set({ status: `nav image: ${(e as Error).message}` });
    } finally {
      set({ busyNav: false });
    }
  },

  showNavImage: async () => {
    const id = get().selectedId;
    if (!id) return;
    set({ busyNav: true });
    try {
      // idempotent server-side, so re-calling this (rather than reusing a
      // cached navMeta) re-registers cleanly even if the user closed the
      // nav image tab since it was last fetched
      const meta = await fetchFourDNav(id);
      set({ navMeta: meta, status: null });
      if (!get().navRaster) set({ navRaster: await fetchData16(meta.id) });
      useViewer.getState().ingestDerived([meta]);
    } catch (e) {
      set({ status: `nav image: ${(e as Error).message}` });
    } finally {
      set({ busyNav: false });
    }
  },

  setProbe: (probe) => set({ probe }),
  setPatternRaster: (patternRaster) => set({ patternRaster }),
  setStatus: (status) => set({ status }),
  setBusyPattern: (busyPattern) => set({ busyPattern }),

  fetchMeanPattern: async () => {
    const id = get().selectedId;
    if (!id) return;
    set({ busyPattern: true });
    try {
      const raster = await fetchFourDMeanPattern(id);
      // a probe click may have already landed while this was in flight —
      // only replace the pattern if we're still showing the mean (no probe)
      if (get().probe === null) set({ patternRaster: raster });
    } catch (e) {
      set({ status: `mean pattern: ${(e as Error).message}` });
    } finally {
      set({ busyPattern: false });
    }
  },

  setApertureMode: (mode) =>
    set((s) => ({
      aperture: {
        ...s.aperture,
        mode,
        ...apertureRadiiForMode(mode, detShapeOf(s.datasets, s.selectedId), s.aperture),
      },
    })),

  setApertureField: (patch) =>
    set((s) => ({ aperture: { ...s.aperture, ...patch, mode: "custom" } })),

  setAutoCenter: (autoCenter) =>
    set((s) => ({ aperture: { ...s.aperture, autoCenter } })),

  computeMap: async () => {
    const { selectedId, aperture, datasets } = get();
    if (!selectedId) return;
    set({ busyCompute: true, status: "computing virtual-detector map…" });
    try {
      const dsName = datasets.find((d) => d.id === selectedId)?.name ?? selectedId;
      const meta = await computeVirtualDetector(selectedId, {
        center_ky: aperture.autoCenter ? null : aperture.centerKy,
        center_kx: aperture.autoCenter ? null : aperture.centerKx,
        inner_r: aperture.innerR,
        outer_r: aperture.outerR,
        shape: aperture.shape,
        name: `${aperture.mode}(${dsName})`,
      });
      useViewer.getState().ingestDerived([meta]);
      set({ status: `map computed → ${meta.name}` });
    } catch (e) {
      set({ status: `virtual-detector: ${(e as Error).message}` });
    } finally {
      set({ busyCompute: false });
    }
  },

  reset: () => set({ ...initial, aperture: defaultAperture([256, 256]) }),
}));
