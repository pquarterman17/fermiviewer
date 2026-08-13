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
  closeFourD,
  computeVirtualDetector,
  fetchData16,
  fetchFourDMeanPattern,
  fetchFourDNav,
  FourDNotFoundError,
  listFourD,
  reshapeFourD,
  type ApertureShape,
  type FourDMeta,
  type ImageMeta,
  type Raster16,
} from "../lib/api";
import { useViewer } from "./viewer";

/** A stale-selection 404 (dataset closed elsewhere, or a selection that
 *  outlived this store's last successful list fetch) degrades to "clear +
 *  refetch" (via `fetchDatasets`) instead of a status note that would just
 *  keep re-failing on every subsequent action (PLAN_4DSTEM #14). */
function isStaleDataset(e: unknown): boolean {
  return e instanceof FourDNotFoundError;
}

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

/** Validate an aperture against what `/virtual-detector` will actually
 *  accept (mirrors `_validate_virtual_detector_request` in
 *  routes/fourd.py) — returns a user-facing reason, or null when the
 *  aperture is safe to send. Checked BEFORE the request goes out so a
 *  stray NaN (e.g. a manual center field mid-edit, which
 *  `JSON.stringify` would otherwise silently collapse to `null` and have
 *  the server reinterpret as "auto-center") or a negative/degenerate
 *  radius never round-trips to the wire at all, rather than relying on
 *  the server's 422 to catch it after the fact. */
export function apertureError(
  aperture: Pick<FourDAperture, "innerR" | "outerR" | "shape" | "autoCenter" | "centerKy" | "centerKx">,
  detShape: readonly [number, number],
): string | null {
  if (!Number.isFinite(aperture.outerR) || aperture.outerR <= 0) {
    return "outer radius must be greater than 0";
  }
  if (aperture.shape === "annulus") {
    if (!Number.isFinite(aperture.innerR) || aperture.innerR < 0) {
      return "inner radius must be 0 or greater";
    }
    if (aperture.innerR >= aperture.outerR) {
      return "inner radius must be smaller than the outer radius";
    }
  }
  if (!aperture.autoCenter) {
    const { centerKy, centerKx } = aperture;
    if (
      centerKy == null || centerKx == null ||
      !Number.isFinite(centerKy) || !Number.isFinite(centerKx)
    ) {
      return "center (ky, kx) must be set when auto-center is off";
    }
    if (
      centerKy < 0 || centerKy > detShape[0] - 1 ||
      centerKx < 0 || centerKx > detShape[1] - 1
    ) {
      return "center (ky, kx) must be within the detector bounds";
    }
  }
  return null;
}

/** A stricter structural check than `isFourDMeta` (which only looks at the
 *  `is_fourd` discriminator, by design — see lib/api/core.ts): this one
 *  additionally verifies the array fields the workshop actually indexes
 *  into (`det_shape`/`scan_shape`/`scan_axes`) are present with the right
 *  shape, so one malformed `/api/fourd` entry can't crash the dataset
 *  picker's render (`d.det_shape.join(...)`) or `probeLabel`'s
 *  `scan_axes` destructure for every OTHER dataset in the list too. Kept
 *  local to this store rather than sharpening `isFourDMeta` itself, since
 *  `isFourDMeta` also discriminates `ingestImages`'s mixed
 *  `ImageMeta | FourDMeta` array — tightening it there would flip a
 *  malformed FourD entry into being treated as a (also-invalid)
 *  ImageMeta instead of being dropped. */
function isValidFourDMeta(m: FourDMeta): boolean {
  return (
    m.is_fourd === true &&
    Array.isArray(m.det_shape) && m.det_shape.length === 2 &&
    Array.isArray(m.scan_shape) && m.scan_shape.length === 2 &&
    Array.isArray(m.scan_axes) && Array.isArray(m.det_axes)
  );
}

interface FourDState {
  datasets: FourDMeta[];
  selectedId: string | null;
  navMeta: ImageMeta | null;
  navRaster: Raster16 | null;
  probe: FourDProbe | null;
  patternRaster: Raster16 | null;
  /** The mean pattern, cached separately from `patternRaster` (which is
   *  overwritten by whatever's currently displayed — mean or a probed
   *  pattern). The server always centers "auto" apertures on the MEAN
   *  pattern's intensity centroid, so the client-side preview ring needs
   *  this even while a probed pattern is on screen. */
  meanRaster: Raster16 | null;
  aperture: FourDAperture;
  busyList: boolean;
  busyNav: boolean;
  busyPattern: boolean;
  busyCompute: boolean;
  status: string | null;

  fetchDatasets: () => Promise<void>;
  selectDataset: (id: string) => Promise<void>;
  /** Re-raster the selected headerless dataset to `rows × cols`. */
  reshapeDataset: (rows: number, cols: number) => Promise<void>;
  closeDataset: (id: string) => Promise<void>;
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
  meanRaster: null as Raster16 | null,
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
      const datasets = (await listFourD()).filter(isValidFourDMeta);
      set((s) => {
        if (!s.selectedId || datasets.some((d) => d.id === s.selectedId)) {
          return { datasets, status: null };
        }
        // The selected dataset is gone server-side (closed elsewhere, or a
        // stale selection surviving past this store's last successful list
        // fetch) — degrade to "cleared selection + refreshed list" instead
        // of leaving per-dataset state that keeps erroring on every action.
        return {
          datasets,
          selectedId: null,
          navMeta: null,
          navRaster: null,
          probe: null,
          patternRaster: null,
          meanRaster: null,
          status: "the selected 4D dataset is no longer open — selection cleared",
        };
      });
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
      meanRaster: null,
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

  reshapeDataset: async (rows, cols) => {
    const id = get().selectedId;
    if (!id) return;
    set({ busyNav: true });
    let meta: FourDMeta;
    try {
      meta = await reshapeFourD(id, rows, cols);
    } catch (e) {
      if (isStaleDataset(e)) await get().fetchDatasets();
      else set({ status: `reshape: ${(e as Error).message}` });
      set({ busyNav: false });
      return;
    }
    // The id is unchanged (routes/fourd.py keeps it deliberately), so the
    // selection survives — but EVERY cached raster described the old raster
    // and none of them describe this one. selectDataset re-fetches them and
    // resets the aperture, which is exactly the teardown needed here; the
    // dataset list is refreshed first so it carries the new shape.
    set({
      datasets: get().datasets.map((d) => (d.id === id ? meta : d)),
      busyNav: false,
    });
    await get().selectDataset(id);
    set({ status: `scan re-rastered to ${rows} × ${cols}` });
  },

  closeDataset: async (id) => {
    try {
      await closeFourD(id);
    } catch (e) {
      set({ status: `close dataset: ${(e as Error).message}` });
      return;
    }
    const wasSelected = get().selectedId === id;
    await get().fetchDatasets();
    // Derived nav/virtual-detector images live in the main viewer store and
    // are untouched server-side (routes/fourd.py's close_fourd docstring) —
    // only this workshop's own 4D-specific state needs clearing, and only
    // when the closed dataset was the one being viewed. fetchDatasets above
    // already self-heals this (its refreshed list no longer contains `id`),
    // but its generic "closed elsewhere" status would be misleading right
    // after a close THIS action just performed — status: null restores the
    // original (silent-success) behaviour for the deliberate-close path.
    if (wasSelected) {
      set({
        selectedId: null,
        navMeta: null,
        navRaster: null,
        probe: null,
        patternRaster: null,
        meanRaster: null,
        status: null,
      });
    }
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
      if (isStaleDataset(e)) await get().fetchDatasets();
      else set({ status: `nav image: ${(e as Error).message}` });
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
      if (isStaleDataset(e)) await get().fetchDatasets();
      else set({ status: `nav image: ${(e as Error).message}` });
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
      // Always cache the mean pattern itself (the auto-center preview needs
      // it even once a probe replaces `patternRaster`). A probe click may
      // have already landed while this was in flight — only replace the
      // currently-displayed pattern if we're still showing the mean (no
      // probe).
      set({ meanRaster: raster });
      if (get().probe === null) set({ patternRaster: raster });
    } catch (e) {
      if (isStaleDataset(e)) await get().fetchDatasets();
      else set({ status: `mean pattern: ${(e as Error).message}` });
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
    const { selectedId, aperture, datasets, busyCompute } = get();
    if (!selectedId || busyCompute) return; // double-submit guard
    const error = apertureError(aperture, detShapeOf(datasets, selectedId));
    if (error) {
      set({ status: `virtual-detector: ${error}` });
      return;
    }
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
      if (isStaleDataset(e)) await get().fetchDatasets();
      else set({ status: `virtual-detector: ${(e as Error).message}` });
    } finally {
      set({ busyCompute: false });
    }
  },

  reset: () => set({ ...initial, aperture: defaultAperture([256, 256]) }),
}));
