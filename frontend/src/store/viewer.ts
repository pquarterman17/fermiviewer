// Single Zustand store — port of the prototype's useFermiViewer() hook
// (handoff §6). Phase 2: display pipeline, measurements, overlay style,
// command-palette / shortcuts / radial chrome.

import { create } from "zustand";

import {
  closeImage as apiClose,
  openSession,
  type ImageMeta,
  type RoiStats,
} from "../lib/api";
import type { ColormapName } from "../lib/colormaps";

/** Per-image view: z = screen px per image px (1 → 100 %),
 *  (px, py) = normalized image point under the viewport centre. */
export interface View {
  z: number;
  px: number;
  py: number;
}

/** Per-image display: lo/hi normalized [0,1] against image min/max. */
export interface Display {
  lo: number;
  hi: number;
  gamma: number;
  cmap: ColormapName;
}

export const DEFAULT_DISPLAY: Display = { lo: 0, hi: 1, gamma: 1, cmap: "gray" };

export type MeasureKind = "distance" | "profile" | "angle" | "roi";

/** Points are normalized 0–1 image coords (handoff §6) so measures
 *  survive crops/derived images of the same aspect. */
export interface Measure {
  id: string;
  kind: MeasureKind;
  pts: { x: number; y: number }[];
}

export interface OverlayStyle {
  size: "S" | "M" | "L" | "XL";
  color: string;
}

export type CaptureMode = "none" | "zoom" | MeasureKind;
export type Theme = "dark" | "light";
export type ListView = "thumbs" | "names";
export type CompareMode = "split" | "flicker" | "subtract";
export type SelectGesture = "single" | "toggle" | "range";

const VIEWS_KEY = "fv_views";
const OVERLAY_KEY = "fv_overlay";

function loadJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

let measureSeq = 0;

interface ViewerState {
  // library
  order: string[];
  activeId: string | null;
  images: Record<string, ImageMeta>;
  selected: string[];
  listView: ListView;
  compareSet: string[] | null;
  compareMode: CompareMode;
  // per-image view, persisted (localStorage "fv_views")
  views: Record<string, View>;
  // per-image display pipeline (window/gamma/colormap)
  display: Record<string, Display>;
  // measurements, per image; selection is a measure id
  measures: Record<string, Measure[]>;
  selectedMeasure: string | null;
  roiStats: Record<string, RoiStats>;
  // display chrome
  theme: Theme;
  overlay: OverlayStyle; // persisted "fv_overlay"
  // tools
  captureMode: CaptureMode;
  panTool: boolean;
  // chrome
  leftCol: boolean;
  rightCol: boolean;
  cmdk: boolean;
  shorts: boolean;
  radial: { x: number; y: number } | null;
  status: string;

  openPaths: (paths: string[]) => Promise<void>;
  setActive: (id: string) => void;
  select: (id: string, gesture: SelectGesture) => void;
  setListView: (v: ListView) => void;
  reorder: (id: string, beforeId: string | null) => void;
  startCompare: (ids: string[]) => void;
  exitCompare: () => void;
  setCompareMode: (m: CompareMode) => void;
  cycleImage: (dir: 1 | -1) => void;
  closeImage: (id: string) => Promise<void>;
  setView: (id: string, view: View) => void;
  setDisplay: (id: string, patch: Partial<Display>) => void;
  addMeasure: (imageId: string, m: Omit<Measure, "id">) => string;
  updateMeasure: (
    imageId: string,
    measureId: string,
    pts: Measure["pts"],
  ) => void;
  removeMeasure: (imageId: string, measureId: string) => void;
  setSelectedMeasure: (id: string | null) => void;
  setRoiStats: (measureId: string, stats: RoiStats) => void;
  setCaptureMode: (mode: CaptureMode) => void;
  setPanTool: (on: boolean) => void;
  setOverlay: (patch: Partial<OverlayStyle>) => void;
  toggleTheme: () => void;
  toggleLeft: () => void;
  toggleRight: () => void;
  setCmdk: (open: boolean) => void;
  setShorts: (open: boolean) => void;
  setRadial: (at: { x: number; y: number } | null) => void;
  setStatus: (msg: string) => void;
}

export const useViewer = create<ViewerState>((set, get) => ({
  order: [],
  activeId: null,
  images: {},
  selected: [],
  listView: "thumbs",
  compareSet: null,
  compareMode: "split",
  views: loadJson<Record<string, View>>(VIEWS_KEY, {}),
  display: {},
  measures: {},
  selectedMeasure: null,
  roiStats: {},
  theme:
    (document.documentElement.getAttribute("data-theme") as Theme) ?? "dark",
  overlay: loadJson<OverlayStyle>(OVERLAY_KEY, { size: "M", color: "#ffffff" }),
  captureMode: "none",
  panTool: false,
  leftCol: false,
  rightCol: false,
  cmdk: false,
  shorts: false,
  radial: null,
  status: "ready",

  openPaths: async (paths) => {
    const metas = await openSession(paths);
    set((s) => {
      const images = { ...s.images };
      const order = [...s.order];
      for (const m of metas) {
        if (!(m.id in images)) order.push(m.id);
        images[m.id] = m;
      }
      const last = metas[metas.length - 1];
      return {
        images,
        order,
        activeId: last ? last.id : s.activeId,
        status: `opened ${metas.length} file${metas.length === 1 ? "" : "s"}`,
      };
    });
  },

  setActive: (id) =>
    set({ activeId: id, selected: [id], selectedMeasure: null }),

  // ⌘/⇧-click multi-select (handoff §9 Library). Range anchors on the
  // last-selected item, in current order.
  select: (id, gesture) => {
    const { selected, order } = get();
    if (gesture === "single") {
      set({ activeId: id, selected: [id], selectedMeasure: null });
      return;
    }
    if (gesture === "toggle") {
      set({
        selected: selected.includes(id)
          ? selected.filter((s) => s !== id)
          : [...selected, id],
      });
      return;
    }
    const anchor = selected[selected.length - 1] ?? id;
    const i = order.indexOf(anchor);
    const j = order.indexOf(id);
    if (i === -1 || j === -1) return;
    set({ selected: order.slice(Math.min(i, j), Math.max(i, j) + 1) });
  },

  setListView: (listView) => set({ listView }),

  /** Drag-reorder: move `id` before `beforeId` (null → end). */
  reorder: (id, beforeId) =>
    set((s) => {
      if (id === beforeId) return {};
      const order = s.order.filter((o) => o !== id);
      const at = beforeId ? order.indexOf(beforeId) : order.length;
      if (at === -1) return {};
      order.splice(at, 0, id);
      return { order };
    }),

  startCompare: (ids) => {
    if (ids.length < 2) return;
    set({ compareSet: ids, captureMode: "none", selectedMeasure: null });
  },

  exitCompare: () => set({ compareSet: null }),
  setCompareMode: (compareMode) => set({ compareMode }),

  cycleImage: (dir) => {
    const { order, activeId } = get();
    if (order.length === 0) return;
    const i = activeId ? order.indexOf(activeId) : 0;
    const next = order[(i + dir + order.length) % order.length];
    set({ activeId: next, selected: [next], selectedMeasure: null });
  },

  closeImage: async (id) => {
    await apiClose(id);
    set((s) => {
      const images = { ...s.images };
      delete images[id];
      const measures = { ...s.measures };
      delete measures[id];
      const order = s.order.filter((o) => o !== id);
      const activeId =
        s.activeId === id ? (order[order.length - 1] ?? null) : s.activeId;
      const compareSet = s.compareSet?.filter((c) => c !== id) ?? null;
      return {
        images,
        order,
        measures,
        activeId,
        selected: s.selected.filter((x) => x !== id),
        compareSet: compareSet && compareSet.length >= 2 ? compareSet : null,
      };
    });
  },

  setView: (id, view) => {
    const views = { ...get().views, [id]: view };
    localStorage.setItem(VIEWS_KEY, JSON.stringify(views));
    set({ views });
  },

  setDisplay: (id, patch) =>
    set((s) => ({
      display: {
        ...s.display,
        [id]: { ...(s.display[id] ?? DEFAULT_DISPLAY), ...patch },
      },
    })),

  addMeasure: (imageId, m) => {
    const id = `m${++measureSeq}`;
    set((s) => ({
      measures: {
        ...s.measures,
        [imageId]: [...(s.measures[imageId] ?? []), { ...m, id }],
      },
      selectedMeasure: id,
    }));
    return id;
  },

  updateMeasure: (imageId, measureId, pts) =>
    set((s) => ({
      measures: {
        ...s.measures,
        [imageId]: (s.measures[imageId] ?? []).map((m) =>
          m.id === measureId ? { ...m, pts } : m,
        ),
      },
    })),

  removeMeasure: (imageId, measureId) =>
    set((s) => {
      const roiStats = { ...s.roiStats };
      delete roiStats[measureId];
      return {
        measures: {
          ...s.measures,
          [imageId]: (s.measures[imageId] ?? []).filter(
            (m) => m.id !== measureId,
          ),
        },
        roiStats,
        selectedMeasure:
          s.selectedMeasure === measureId ? null : s.selectedMeasure,
      };
    }),

  setSelectedMeasure: (id) => set({ selectedMeasure: id }),
  setRoiStats: (measureId, stats) =>
    set((s) => ({ roiStats: { ...s.roiStats, [measureId]: stats } })),

  setCaptureMode: (mode) => set({ captureMode: mode }),
  setPanTool: (on) => set({ panTool: on }),

  setOverlay: (patch) => {
    const overlay = { ...get().overlay, ...patch };
    localStorage.setItem(OVERLAY_KEY, JSON.stringify(overlay));
    set({ overlay });
  },

  toggleTheme: () => {
    const theme: Theme = get().theme === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", theme);
    set({ theme });
  },

  toggleLeft: () => set((s) => ({ leftCol: !s.leftCol })),
  toggleRight: () => set((s) => ({ rightCol: !s.rightCol })),
  setCmdk: (cmdk) => set({ cmdk }),
  setShorts: (shorts) => set({ shorts }),
  setRadial: (radial) => set({ radial }),
  setStatus: (msg) => set({ status: msg }),
}));
