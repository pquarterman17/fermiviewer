// Single Zustand store — port of the prototype's useFermiViewer() hook
// (handoff §6). Phase 2: display pipeline, measurements, overlay style,
// command-palette / shortcuts / radial chrome.

import { create } from "zustand";

import {
  closeImage as apiClose,
  loadSession,
  openSession,
  saveSession,
  uploadFiles,
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
  invert: boolean;
}

export const DEFAULT_DISPLAY: Display = {
  lo: 0,
  hi: 1,
  gamma: 1,
  cmap: "gray",
  invert: false,
};

export type MeasureKind =
  | "distance"
  | "profile"
  | "angle"
  | "roi"
  | "polyline";

/** Points are normalized 0–1 image coords (handoff §6) so measures
 *  survive crops/derived images of the same aspect. */
export interface Measure {
  id: string;
  kind: MeasureKind;
  pts: { x: number; y: number }[];
}

/** Undoable mutations (Edit menu / ⌘Z). Derived-image entries remove
 *  only the CLIENT registration — the server keeps the DataStruct for
 *  the session, which is what makes redo instant and lossless. */
export type UndoEntry =
  | { t: "measure-add"; imageId: string; measure: Measure }
  | { t: "measure-del"; imageId: string; measure: Measure }
  | {
      t: "measure-move";
      imageId: string;
      measureId: string;
      before: Measure["pts"];
      after: Measure["pts"];
    }
  | { t: "derived"; meta: ImageMeta; parentId: string };

export function undoLabel(e: UndoEntry): string {
  switch (e.t) {
    case "measure-add":
      return `add ${e.measure.kind}`;
    case "measure-del":
      return `delete ${e.measure.kind}`;
    case "measure-move":
      return "move measure";
    case "derived":
      return e.meta.name;
  }
}

const UNDO_CAP = 99;

export interface OverlayStyle {
  size: "S" | "M" | "L" | "XL";
  color: string;
}

export type CaptureMode = "none" | "zoom" | MeasureKind;
export type Theme = "dark" | "light";
export type ListView = "thumbs" | "names";
export type CompareMode = "split" | "flicker" | "subtract";
export type SelectGesture = "single" | "toggle" | "range";
export type ToolKind = "eels" | "eds" | "diffraction" | "fftmask";

export interface ToolWindowState {
  kind: ToolKind;
  x: number;
  y: number;
  z: number;
}

const VIEWS_KEY = "fv_views";
const OVERLAY_KEY = "fv_overlay";
const THEME_KEY = "fv_theme";

function initialTheme(): Theme {
  // persisted preference wins; otherwise follow the OS (checklist N)
  const stored = localStorage.getItem(THEME_KEY);
  if (stored === "dark" || stored === "light") return stored;
  return window.matchMedia?.("(prefers-color-scheme: light)").matches
    ? "light"
    : "dark";
}

function loadJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

let measureSeq = 0;

type SetState = (
  fn: (s: { images: Record<string, ImageMeta>; order: string[]; activeId: string | null }) => object,
) => void;

/** Merge newly opened images into the library (shared by path + upload). */
function _ingest(set: SetState, metas: ImageMeta[]): void {
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
}

type SetFull = (fn: (s: ViewerState) => Partial<ViewerState>) => void;

/** Apply one undo entry in the given direction (pure state surgery —
 *  never calls the public actions, so no re-push loops). */
function applyUndoEntry(set: SetFull, e: UndoEntry, dir: "undo" | "redo"): void {
  const inverse = dir === "undo";
  switch (e.t) {
    case "measure-add":
    case "measure-del": {
      const doRemove = (e.t === "measure-add") === inverse;
      if (doRemove) {
        set((s) => ({
          measures: {
            ...s.measures,
            [e.imageId]: (s.measures[e.imageId] ?? []).filter(
              (m) => m.id !== e.measure.id,
            ),
          },
          selectedMeasure:
            s.selectedMeasure === e.measure.id ? null : s.selectedMeasure,
        }));
      } else {
        set((s) => ({
          measures: {
            ...s.measures,
            [e.imageId]: [...(s.measures[e.imageId] ?? []), e.measure],
          },
        }));
      }
      break;
    }
    case "measure-move":
      set((s) => ({
        measures: {
          ...s.measures,
          [e.imageId]: (s.measures[e.imageId] ?? []).map((m) =>
            m.id === e.measureId
              ? { ...m, pts: inverse ? e.before : e.after }
              : m,
          ),
        },
      }));
      break;
    case "derived":
      if (inverse) {
        set((s) => {
          const images = { ...s.images };
          delete images[e.meta.id];
          return {
            images,
            order: s.order.filter((i) => i !== e.meta.id),
            selected: s.selected.filter((i) => i !== e.meta.id),
            activeId:
              s.activeId === e.meta.id
                ? e.parentId in images
                  ? e.parentId
                  : null
                : s.activeId,
          };
        });
      } else {
        set((s) => ({
          images: { ...s.images, [e.meta.id]: e.meta },
          order: s.order.includes(e.meta.id)
            ? s.order
            : [...s.order, e.meta.id],
          activeId: e.meta.id,
        }));
      }
      break;
  }
}

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
  // undo/redo (Edit menu)
  undoStack: UndoEntry[];
  redoStack: UndoEntry[];
  // display chrome
  theme: Theme;
  overlay: OverlayStyle; // persisted "fv_overlay"
  // tools
  captureMode: CaptureMode;
  panTool: boolean;
  profileWidth: number; // ⊥ averaging width (px) for profile captures
  // chrome
  leftCol: boolean;
  rightCol: boolean;
  cmdk: boolean;
  shorts: boolean;
  radial: { x: number; y: number } | null;
  tools: ToolWindowState[]; // open workshop windows (handoff §6)
  exportOpen: boolean;
  calibOpen: boolean;
  status: string;

  openPaths: (paths: string[]) => Promise<void>;
  openFiles: (files: FileList | File[]) => Promise<void>;
  ingest: (metas: ImageMeta[]) => void;
  saveWorkspace: (path: string) => Promise<void>;
  loadWorkspace: (path: string) => Promise<void>;
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
  ingestDerived: (metas: ImageMeta[]) => void;
  pushUndo: (e: UndoEntry) => void;
  undo: () => UndoEntry | null;
  redo: () => UndoEntry | null;
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
  setProfileWidth: (w: number) => void;
  setOverlay: (patch: Partial<OverlayStyle>) => void;
  toggleTheme: () => void;
  toggleLeft: () => void;
  toggleRight: () => void;
  setCmdk: (open: boolean) => void;
  setShorts: (open: boolean) => void;
  setRadial: (at: { x: number; y: number } | null) => void;
  openTool: (kind: ToolKind) => void;
  closeTool: (kind: ToolKind) => void;
  focusTool: (kind: ToolKind) => void;
  moveTool: (kind: ToolKind, x: number, y: number) => void;
  setExportOpen: (open: boolean) => void;
  setCalibOpen: (open: boolean) => void;
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
  undoStack: [],
  redoStack: [],
  theme: (() => {
    const t = initialTheme();
    document.documentElement.setAttribute("data-theme", t);
    return t;
  })(),
  overlay: loadJson<OverlayStyle>(OVERLAY_KEY, { size: "M", color: "#ffffff" }),
  captureMode: "none",
  panTool: false,
  profileWidth: 1,
  leftCol: false,
  rightCol: false,
  cmdk: false,
  shorts: false,
  radial: null,
  tools: [],
  exportOpen: false,
  calibOpen: false,
  status: "ready",

  openPaths: async (paths) => {
    _ingest(set, await openSession(paths));
  },

  openFiles: async (files) => {
    _ingest(set, await uploadFiles(files));
  },

  /** Register derived/analysis result images in the library. */
  ingest: (metas) => _ingest(set, metas),

  /** Like ingest, but records each image on the undo stack (used by
   *  single-result operations: filters, transforms, FFT masks…). */
  ingestDerived: (metas) => {
    _ingest(set, metas);
    set((s) => ({
      undoStack: [
        ...s.undoStack.slice(-UNDO_CAP),
        ...metas.map((m) => ({
          t: "derived" as const,
          meta: m,
          parentId: String(m.meta["derived_from"] ?? ""),
        })),
      ],
      redoStack: [],
    }));
  },

  pushUndo: (e) =>
    set((s) => ({
      undoStack: [...s.undoStack.slice(-UNDO_CAP), e],
      redoStack: [],
    })),

  undo: () => {
    const e = get().undoStack.at(-1);
    if (!e) return null;
    applyUndoEntry(set, e, "undo");
    set((s) => ({
      undoStack: s.undoStack.slice(0, -1),
      redoStack: [...s.redoStack, e],
    }));
    return e;
  },

  redo: () => {
    const e = get().redoStack.at(-1);
    if (!e) return null;
    applyUndoEntry(set, e, "redo");
    set((s) => ({
      redoStack: s.redoStack.slice(0, -1),
      undoStack: [...s.undoStack, e],
    }));
    return e;
  },

  saveWorkspace: async (path) => {
    const s = get();
    const r = await saveSession(path, {
      order: s.order,
      activeId: s.activeId,
      views: s.views,
      display: s.display,
      measures: s.measures,
      overlay: s.overlay,
    });
    set({ status: `saved ${r.n_images} images → ${r.json_path}` });
  },

  loadWorkspace: async (path) => {
    const r = await loadSession(path);
    const images: Record<string, ImageMeta> = {};
    for (const m of r.images) images[m.id] = m;
    const cs = r.client_state ?? {};
    // saved order filtered to what actually loaded; fall back to manifest order
    const loadedIds = r.images.map((m) => m.id);
    const order = (
      (cs.order as string[] | undefined)?.filter((id) => id in images) ??
      loadedIds
    ).concat(loadedIds.filter((id) => !(cs.order as string[])?.includes(id)));
    const activeId =
      typeof cs.activeId === "string" && cs.activeId in images
        ? cs.activeId
        : (order[0] ?? null);
    set({
      images,
      order,
      activeId,
      selected: activeId ? [activeId] : [],
      compareSet: null,
      selectedMeasure: null,
      views: (cs.views as Record<string, View>) ?? {},
      display: (cs.display as Record<string, Display>) ?? {},
      measures: (cs.measures as Record<string, Measure[]>) ?? {},
      overlay: (cs.overlay as OverlayStyle) ?? get().overlay,
      status: `loaded ${r.images.length} images`,
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
    const measure = { ...m, id };
    set((s) => ({
      measures: {
        ...s.measures,
        [imageId]: [...(s.measures[imageId] ?? []), measure],
      },
      selectedMeasure: id,
      undoStack: [
        ...s.undoStack.slice(-UNDO_CAP),
        { t: "measure-add" as const, imageId, measure },
      ],
      redoStack: [],
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
      const victim = (s.measures[imageId] ?? []).find(
        (m) => m.id === measureId,
      );
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
        ...(victim && {
          undoStack: [
            ...s.undoStack.slice(-UNDO_CAP),
            { t: "measure-del" as const, imageId, measure: victim },
          ],
          redoStack: [],
        }),
      };
    }),

  setSelectedMeasure: (id) => set({ selectedMeasure: id }),
  setRoiStats: (measureId, stats) =>
    set((s) => ({ roiStats: { ...s.roiStats, [measureId]: stats } })),

  setCaptureMode: (mode) => set({ captureMode: mode }),
  setProfileWidth: (w) =>
    set({ profileWidth: Math.max(1, Math.min(99, Math.round(w))) }),
  setPanTool: (on) => set({ panTool: on }),

  setOverlay: (patch) => {
    const overlay = { ...get().overlay, ...patch };
    localStorage.setItem(OVERLAY_KEY, JSON.stringify(overlay));
    set({ overlay });
  },

  toggleTheme: () => {
    const theme: Theme = get().theme === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(THEME_KEY, theme);
    set({ theme });
  },

  toggleLeft: () => set((s) => ({ leftCol: !s.leftCol })),
  toggleRight: () => set((s) => ({ rightCol: !s.rightCol })),
  setCmdk: (cmdk) => set({ cmdk }),
  setShorts: (shorts) => set({ shorts }),
  setRadial: (radial) => set({ radial }),

  // one window per kind; opening an existing one refocuses it (§4)
  openTool: (kind) =>
    set((s) => {
      const zTop = Math.max(0, ...s.tools.map((t) => t.z)) + 1;
      if (s.tools.some((t) => t.kind === kind)) {
        return {
          tools: s.tools.map((t) =>
            t.kind === kind ? { ...t, z: zTop } : t,
          ),
        };
      }
      const offset = s.tools.length * 32;
      return {
        tools: [
          ...s.tools,
          { kind, x: 140 + offset, y: 110 + offset, z: zTop },
        ],
      };
    }),

  closeTool: (kind) =>
    set((s) => ({ tools: s.tools.filter((t) => t.kind !== kind) })),

  focusTool: (kind) =>
    set((s) => {
      const zTop = Math.max(0, ...s.tools.map((t) => t.z)) + 1;
      return {
        tools: s.tools.map((t) => (t.kind === kind ? { ...t, z: zTop } : t)),
      };
    }),

  moveTool: (kind, x, y) =>
    set((s) => ({
      tools: s.tools.map((t) => (t.kind === kind ? { ...t, x, y } : t)),
    })),

  setExportOpen: (exportOpen) => set({ exportOpen }),
  setCalibOpen: (calibOpen) => set({ calibOpen }),
  setStatus: (msg) => set({ status: msg }),
}));
