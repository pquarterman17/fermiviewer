// Single Zustand store — port of the prototype's useFermiViewer() hook
// (handoff §6). Phase 2: display pipeline, measurements, overlay style,
// command-palette / shortcuts / radial chrome.

import { create } from "zustand";

import {
  closeImage as apiClose,
  loadSession,
  loadWorkspaceNamed as apiLoadWorkspaceNamed,
  openSession,
  saveSession,
  saveWorkspaceNamed as apiSaveWorkspaceNamed,
  uploadFiles,
  type ImageMeta,
  type RoiStats,
  type SessionClientState,
} from "../lib/api";
import type { ColormapName } from "../lib/colormaps";
import { logStatus } from "../lib/errlog";
import type { TiltSettings } from "../lib/geometry";

export type { TiltSettings };

/** Per-image view: z = screen px per image px (1 → 100 %),
 *  (px, py) = normalized image point under the viewport centre. */
export interface View {
  z: number;
  px: number;
  py: number;
}

/** Per-image display: lo/hi normalized [0,1] against image min/max. */
export type DisplayTransform = "linear" | "log" | "equalize";

export interface Display {
  lo: number;
  hi: number;
  gamma: number;
  cmap: ColormapName;
  invert: boolean;
  /** intensity transform applied to the texture before window/γ/LUT */
  transform: DisplayTransform;
  /** colorbar tick interval in real value units (nm for AFM); 0/undefined = auto */
  tickStep?: number;
}

export type ColorbarSide = "left" | "right";

export const DEFAULT_DISPLAY: Display = {
  lo: 0,
  hi: 1,
  gamma: 1,
  cmap: "gray",
  invert: false,
  transform: "linear",
};

export type MeasureKind =
  | "distance"
  | "profile"
  | "angle"
  | "roi"
  | "ellipse"
  | "polyline"
  // annotations (checklist H) — ride the measure rails: overlay
  // rendering, persistence, undo and export baking all come free
  | "text"
  | "arrow"
  | "box"
  | "circle";

export type EndSymbol = "bar" | "circle" | "cross" | "square" | "none";

/** Points are normalized 0–1 image coords (handoff §6) so measures
 *  survive crops/derived images of the same aspect. */
export interface Measure {
  id: string;
  kind: MeasureKind;
  pts: { x: number; y: number }[];
  /** annotation caption (text / arrow / box kinds) */
  text?: string;
  /** per-item colour override (falls back to the overlay style) */
  color?: string;
  /** dragged label offset in screen px (from the default anchor) */
  labelDx?: number;
  labelDy?: number;
  /** endpoint glyph override (falls back to overlay style default) */
  endSymbol?: EndSymbol;
  /** ⊥ averaging width in image px (box-profile captures); falls back
   *  to the global profileWidth when absent */
  width?: number;
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
  endSymbol: EndSymbol;
}

/** Per-image scale bar display overrides.
 *  x/y are fractional positions 0–1 relative to the stage viewport
 *  (default bottom-left ≈ 0.02, 0.92).
 *  lengthPhys null means auto (nice-number); thickness/fontSize null = auto. */
export interface ScaleBarState {
  x: number;          // normalized stage x (0 = left, 1 = right)
  y: number;          // normalized stage y (0 = top, 1 = bottom)
  lengthPhys: number | null;  // physical length override (in pixel_unit)
  thickness: number | null;   // bar thickness in screen px (null = auto)
  fontSize: number | null;    // label font size in px (null = auto)
}

export type CaptureMode =
  | "none"
  | "zoom"
  | "fixed-zoom"
  | "box-profile"
  | MeasureKind;
export type Theme = "dark" | "light";
/** Swappable accent scheme (kept in sync with lib/prefs Accent; no import
 *  to avoid an init-time cycle, same as Theme vs ThemeChoice). */
export type Accent = "violet" | "teal" | "ocean" | "amber" | "rose";
/** UI density — drives the spacing/row-height/font-size token block. */
export type Density = "compact" | "regular" | "comfy";
export type ListView = "thumbs" | "names";
export type CompareMode = "split" | "flicker" | "subtract";
export type SelectGesture = "single" | "toggle" | "range";
export type ToolKind =
  | "eels"
  | "eds"
  | "diffraction"
  | "fftmask"
  | "pixels"
  | "structure"
  | "overlay"
  | "surface";

export interface ToolWindowState {
  kind: ToolKind;
  x: number;
  y: number;
  z: number;
}

const VIEWS_KEY = "fv_views";
const OVERLAY_KEY = "fv_overlay";
const THEME_KEY = "fv_theme";

/** Resolve the OS colour-scheme to a concrete theme. */
function systemTheme(): Theme {
  return window.matchMedia?.("(prefers-color-scheme: light)").matches
    ? "light"
    : "dark";
}

function initialTheme(): Theme {
  // explicit persisted choice wins; "system"/absent follow the OS (checklist N)
  const stored = localStorage.getItem(THEME_KEY);
  if (stored === "dark" || stored === "light") return stored;
  return systemTheme();
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
  fn: (s: {
    images: Record<string, ImageMeta>;
    order: string[];
    activeId: string | null;
    tilts: Record<string, TiltSettings>;
  }) => object,
) => void;

/** Read one persisted preference with a fallback (lib/prefs.ts owns
 *  the dialog; this avoids an import cycle at store-init time). */
function _pref<T>(key: string, fallback: T): T {
  try {
    const p = JSON.parse(localStorage.getItem("fv_prefs") ?? "{}") as Record<
      string,
      T
    >;
    return p[key] ?? fallback;
  } catch {
    return fallback;
  }
}

/** Merge one key into the persisted fv_prefs blob (used by the live-apply
 *  store actions so a change made in the inspector sticks across reloads). */
function writePref(key: string, value: unknown): void {
  try {
    const p = JSON.parse(localStorage.getItem("fv_prefs") ?? "{}") as Record<
      string,
      unknown
    >;
    localStorage.setItem("fv_prefs", JSON.stringify({ ...p, [key]: value }));
  } catch {
    /* ignore quota / serialization errors — non-persistence is non-fatal */
  }
}

/** Merge newly opened images into the library (shared by path + upload). */
function _ingest(set: SetState, metas: ImageMeta[]): void {
  // preferences applied to images seen for the first time
  let prefCmap = "gray";
  let prefTransform: Display["transform"] = "linear";
  let prefInvert = false;
  let prefTiltGeom: "cross-section" | "surface" = "cross-section";
  try {
    const p = JSON.parse(localStorage.getItem("fv_prefs") ?? "{}") as {
      defaultCmap?: string;
      defaultTransform?: Display["transform"];
      defaultInvert?: boolean;
      tiltGeometry?: "cross-section" | "surface";
    };
    prefCmap = p.defaultCmap ?? "gray";
    prefTransform = p.defaultTransform ?? "linear";
    prefInvert = p.defaultInvert ?? false;
    prefTiltGeom = p.tiltGeometry ?? "cross-section";
  } catch {
    /* defaults */
  }
  set((s) => {
    const images = { ...s.images };
    const order = [...s.order];
    const tilts = { ...s.tilts };
    const display = {
      ...(s as unknown as { display: Record<string, Display> }).display,
    };
    for (const m of metas) {
      if (!(m.id in images)) {
        order.push(m.id);
        // seed display only when a default differs from the built-ins, so
        // the common case leaves display[id] unset and Stage's DM-window
        // seeding still runs on first load
        if (
          (prefCmap !== "gray" || prefTransform !== "linear" || prefInvert) &&
          !(m.id in display)
        ) {
          display[m.id] = {
            ...DEFAULT_DISPLAY,
            cmap: prefCmap as Display["cmap"],
            transform: prefTransform,
            invert: prefInvert,
          };
        }
        // #34: seed tilt from stage metadata; angle 0 keeps it off
        // until the user enables it in the Tilt card
        if (m.stage_tilt_deg != null && !(m.id in tilts)) {
          tilts[m.id] = {
            angle: 0,
            seedAngle: m.stage_tilt_deg,
            axis: "Y",
            geometry: prefTiltGeom,
          };
        }
      }
      images[m.id] = m;
    }
    const last = metas[metas.length - 1];
    return {
      images,
      order,
      tilts,
      display,
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

/** The named workspace currently loaded (null = an unsaved "Default"
 *  session). Drives the menu-bar workspace switcher (design WS4b). */
export interface WorkspaceRef {
  slug: string;
  name: string;
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
  accent: Accent;
  density: Density;
  overlay: OverlayStyle; // persisted "fv_overlay"
  // per-image scale bar position/size overrides
  scaleBars: Record<string, ScaleBarState>;
  // per-image tilt-correction settings (#34); absent = off
  tilts: Record<string, TiltSettings>;
  // per-image stack frame index (0-based; only relevant for spectrum_image)
  stackFrames: Record<string, number>;
  /** fixed-zoom dimensions in image pixels (A2 capture mode) */
  fixedZoomW: number;
  fixedZoomH: number;
  // tools
  captureMode: CaptureMode;
  panTool: boolean;
  profileWidth: number;  // ⊥ averaging width (px) for profile captures
  profileReduce: "mean" | "sum"; // box/profile reduction mode (item #49)
  toolsLayout: "cards" | "unified"; // inspector tools layout (persisted pref)
  // chrome
  leftCol: boolean;
  rightCol: boolean;
  minimap: boolean;
  colorbar: boolean;
  colorbarSide: ColorbarSide; // persisted "colorbarSide" pref
  scaleBarVisible: boolean;
  cmdk: boolean;
  shorts: boolean;
  radial: { x: number; y: number } | null;
  tools: ToolWindowState[]; // open workshop windows (handoff §6)
  exportOpen: boolean;
  batchOpen: boolean;
  calibOpen: boolean;
  metaOpen: boolean;
  prefsOpen: boolean;
  galleryOpen: boolean;
  status: string;
  currentWorkspace: WorkspaceRef | null;

  openPaths: (paths: string[]) => Promise<void>;
  openFiles: (files: FileList | File[]) => Promise<void>;
  ingest: (metas: ImageMeta[]) => void;
  saveWorkspace: (path: string) => Promise<void>;
  loadWorkspace: (path: string) => Promise<void>;
  saveWorkspaceNamed: (name: string) => Promise<void>;
  loadWorkspaceNamed: (slug: string) => Promise<void>;
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
  setMeasureText: (imageId: string, measureId: string, text: string) => void;
  setMeasureStyle: (
    imageId: string,
    measureId: string,
    patch: Partial<Pick<Measure, "color" | "labelDx" | "labelDy" | "endSymbol">>,
  ) => void;
  /** marquee multi-selection (shift-drag on the stage) */
  selectedMulti: string[];
  setSelectedMulti: (ids: string[]) => void;
  /** Remove all measures (or only the given kinds), undoably. */
  clearMeasures: (imageId: string, kinds: MeasureKind[] | null) => void;
  setSelectedMeasure: (id: string | null) => void;
  setRoiStats: (measureId: string, stats: RoiStats) => void;
  setCaptureMode: (mode: CaptureMode) => void;
  setPanTool: (on: boolean) => void;
  setProfileWidth: (w: number) => void;
  setProfileReduce: (r: "mean" | "sum") => void;
  setToolsLayout: (v: "cards" | "unified") => void;
  setOverlay: (patch: Partial<OverlayStyle>) => void;
  setScaleBar: (imageId: string, patch: Partial<ScaleBarState>) => void;
  /** Set or clear (null) the per-image tilt correction (#34). */
  setTilt: (imageId: string, t: TiltSettings | null) => void;
  setStackFrame: (imageId: string, frame: number) => void;
  setFixedZoomDims: (w: number, h: number) => void;
  setTheme: (choice: Theme | "system") => void;
  toggleTheme: () => void;
  setAccent: (accent: Accent) => void;
  setDensity: (density: Density) => void;
  setScaleBarVisible: (on: boolean) => void;
  toggleLeft: () => void;
  toggleRight: () => void;
  toggleMinimap: () => void;
  toggleColorbar: () => void;
  setColorbarSide: (side: ColorbarSide) => void;
  toggleScaleBar: () => void;
  setCmdk: (open: boolean) => void;
  setShorts: (open: boolean) => void;
  setRadial: (at: { x: number; y: number } | null) => void;
  openTool: (kind: ToolKind) => void;
  closeTool: (kind: ToolKind) => void;
  focusTool: (kind: ToolKind) => void;
  moveTool: (kind: ToolKind, x: number, y: number) => void;
  setExportOpen: (open: boolean) => void;
  setBatchOpen: (open: boolean) => void;
  setCalibOpen: (open: boolean) => void;
  setMetaOpen: (open: boolean) => void;
  setPrefsOpen: (open: boolean) => void;
  setGalleryOpen: (open: boolean) => void;
  setStatus: (msg: string) => void;
}

/** The serializable slice of store state a saved session captures —
 *  shared by every save path (file + named workspace). */
function _clientState(s: ViewerState): SessionClientState {
  return {
    order: s.order,
    activeId: s.activeId,
    views: s.views,
    display: s.display,
    measures: s.measures,
    overlay: s.overlay,
  };
}

/** Build the store slice that a loaded session replaces — shared by
 *  loadWorkspace (arbitrary path) and loadWorkspaceNamed (config-dir
 *  workspace) so both restore identical state (status + currentWorkspace
 *  are added by each caller). */
function sessionSlice(
  r: { images: ImageMeta[]; client_state: SessionClientState | null },
  fallbackOverlay: OverlayStyle,
): Partial<ViewerState> {
  const images: Record<string, ImageMeta> = {};
  for (const m of r.images) images[m.id] = m;
  const cs = r.client_state ?? {};
  const savedOrder = cs.order as string[] | undefined;
  const loadedIds = r.images.map((m) => m.id);
  // saved order filtered to what actually loaded; append any newcomers
  const order = (savedOrder?.filter((id) => id in images) ?? loadedIds).concat(
    loadedIds.filter((id) => !savedOrder?.includes(id)),
  );
  const activeId =
    typeof cs.activeId === "string" && cs.activeId in images
      ? cs.activeId
      : (order[0] ?? null);
  return {
    images,
    order,
    activeId,
    selected: activeId ? [activeId] : [],
    compareSet: null,
    selectedMeasure: null,
    selectedMulti: [],
    views: (cs.views as Record<string, View>) ?? {},
    display: (cs.display as Record<string, Display>) ?? {},
    measures: (cs.measures as Record<string, Measure[]>) ?? {},
    overlay: (cs.overlay as OverlayStyle) ?? fallbackOverlay,
    // a load is a fresh session: drop undo history + per-image state that
    // isn't part of the saved payload so it doesn't bleed across loads
    undoStack: [],
    redoStack: [],
    scaleBars: {},
    tilts: {},
    stackFrames: {},
    roiStats: {},
  };
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
  accent: (() => {
    const a = _pref<Accent>("accent", "violet");
    document.documentElement.setAttribute("data-accent", a);
    return a;
  })(),
  density: (() => {
    const d = _pref<Density>("density", "regular");
    document.documentElement.setAttribute("data-density", d);
    return d;
  })(),
  // default endSymbol "bar" (user request 2026-06-09): dimension-style
  // perpendicular ticks at measurement line ends
  overlay: loadJson<OverlayStyle>(OVERLAY_KEY, { size: "M", color: "#ffffff", endSymbol: "bar" }),
  scaleBars: {},
  tilts: {},
  stackFrames: {},
  fixedZoomW: _pref("fixedZoomW", 256),
  fixedZoomH: _pref("fixedZoomH", 256),
  captureMode: "none",
  panTool: false,
  profileWidth: _pref("profileWidth", 1),
  profileReduce: _pref<"mean" | "sum">("profileReduce", "mean"),
  toolsLayout: _pref<"cards" | "unified">(
    "toolsLayout",
    localStorage.getItem("fv_tools_layout") === "unified" ? "unified" : "cards",
  ),
  leftCol: false,
  minimap: _pref("minimap", true),
  colorbar: _pref("colorbarOnByDefault", false),
  colorbarSide: _pref<ColorbarSide>("colorbarSide", "right"),
  scaleBarVisible: _pref("scaleBarVisible", true),
  rightCol: false,
  cmdk: false,
  shorts: false,
  radial: null,
  tools: [],
  exportOpen: false,
  batchOpen: false,
  calibOpen: false,
  metaOpen: false,
  prefsOpen: false,
  galleryOpen: false,
  status: "ready",
  currentWorkspace: null,

  openPaths: async (paths) => {
    _ingest(set, await openSession(paths));
    // recent-files list (checklist L) — successful path-opens only
    try {
      const prev = JSON.parse(
        localStorage.getItem("fv_recent") ?? "[]",
      ) as string[];
      const next = [...paths, ...prev.filter((p) => !paths.includes(p))];
      localStorage.setItem("fv_recent", JSON.stringify(next.slice(0, 8)));
    } catch {
      /* quota/parse — recents are best-effort */
    }
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

  // current client state as the serializable session payload
  saveWorkspace: async (path) => {
    const s = get();
    const r = await saveSession(path, _clientState(s));
    set({ status: `saved ${r.n_images} images → ${r.json_path}` });
  },

  loadWorkspace: async (path) => {
    const r = await loadSession(path);
    set({
      ...sessionSlice(r, get().overlay),
      // an ad-hoc file load isn't a named workspace
      currentWorkspace: null,
      status: `loaded ${r.images.length} images`,
    });
  },

  saveWorkspaceNamed: async (name) => {
    const r = await apiSaveWorkspaceNamed(name, _clientState(get()));
    set({
      currentWorkspace: { slug: r.slug, name: r.name },
      status: `saved workspace “${r.name}” · ${r.n_images} images`,
    });
  },

  loadWorkspaceNamed: async (slug) => {
    const r = await apiLoadWorkspaceNamed(slug);
    set({
      ...sessionSlice(r, get().overlay),
      currentWorkspace: { slug, name: r.name },
      status: `opened workspace “${r.name}” · ${r.images.length} images`,
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
      const closed = measures[id] ?? [];
      delete measures[id];
      const order = s.order.filter((o) => o !== id);
      const activeId =
        s.activeId === id ? (order[order.length - 1] ?? null) : s.activeId;
      const compareSet = s.compareSet?.filter((c) => c !== id) ?? null;
      // drop the closed image's per-image state so these maps don't grow
      // unbounded across an open/close-heavy session (and evict its
      // persisted view from localStorage)
      const views = { ...s.views };
      delete views[id];
      const display = { ...s.display };
      delete display[id];
      const scaleBars = { ...s.scaleBars };
      delete scaleBars[id];
      const tilts = { ...s.tilts };
      delete tilts[id];
      const stackFrames = { ...s.stackFrames };
      delete stackFrames[id];
      const roiStats = { ...s.roiStats };
      for (const m of closed) delete roiStats[m.id];
      localStorage.setItem(VIEWS_KEY, JSON.stringify(views));
      return {
        images,
        order,
        measures,
        activeId,
        selected: s.selected.filter((x) => x !== id),
        compareSet: compareSet && compareSet.length >= 2 ? compareSet : null,
        views,
        display,
        scaleBars,
        tilts,
        stackFrames,
        roiStats,
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

  setMeasureText: (imageId, measureId, text) =>
    set((s) => ({
      measures: {
        ...s.measures,
        [imageId]: (s.measures[imageId] ?? []).map((m) =>
          m.id === measureId ? { ...m, text } : m,
        ),
      },
    })),

  setMeasureStyle: (imageId, measureId, patch) =>
    set((s) => ({
      measures: {
        ...s.measures,
        [imageId]: (s.measures[imageId] ?? []).map((m) =>
          m.id === measureId ? { ...m, ...patch } : m,
        ),
      },
    })),

  selectedMulti: [],
  setSelectedMulti: (selectedMulti) => set({ selectedMulti }),

  clearMeasures: (imageId, kinds) =>
    set((s) => {
      const all = s.measures[imageId] ?? [];
      const victims = kinds
        ? all.filter((m) => kinds.includes(m.kind))
        : all;
      if (victims.length === 0) return {};
      const keep = all.filter((m) => !victims.includes(m));
      const roiStats = { ...s.roiStats };
      for (const v of victims) delete roiStats[v.id];
      return {
        measures: { ...s.measures, [imageId]: keep },
        roiStats,
        selectedMeasure: victims.some((v) => v.id === s.selectedMeasure)
          ? null
          : s.selectedMeasure,
        undoStack: [
          ...s.undoStack.slice(-UNDO_CAP),
          ...victims.map((measure) => ({
            t: "measure-del" as const,
            imageId,
            measure,
          })),
        ],
        redoStack: [],
      };
    }),

  setSelectedMeasure: (id) => set({ selectedMeasure: id }),
  setRoiStats: (measureId, stats) =>
    set((s) => ({ roiStats: { ...s.roiStats, [measureId]: stats } })),

  setCaptureMode: (mode) => set({ captureMode: mode }),
  setProfileWidth: (w) => {
    const profileWidth = Math.max(1, Math.min(99, Math.round(w)));
    writePref("profileWidth", profileWidth);
    set({ profileWidth });
  },
  setProfileReduce: (r) => {
    writePref("profileReduce", r);
    set({ profileReduce: r });
  },
  setToolsLayout: (v) => {
    writePref("toolsLayout", v);
    set({ toolsLayout: v });
  },
  setPanTool: (on) => set({ panTool: on }),

  setOverlay: (patch) => {
    const overlay = { ...get().overlay, ...patch };
    localStorage.setItem(OVERLAY_KEY, JSON.stringify(overlay));
    set({ overlay });
  },

  setScaleBar: (imageId, patch) =>
    set((s) => {
      const prev = s.scaleBars[imageId] ?? {
        x: 0.02, y: 0.92, lengthPhys: null, thickness: null, fontSize: null,
      };
      return { scaleBars: { ...s.scaleBars, [imageId]: { ...prev, ...patch } } };
    }),

  setStackFrame: (imageId, frame) =>
    set((s) => ({ stackFrames: { ...s.stackFrames, [imageId]: frame } })),

  setTilt: (imageId, t) =>
    set((s) => {
      const tilts = { ...s.tilts };
      if (t === null) delete tilts[imageId];
      else tilts[imageId] = t;
      return { tilts };
    }),

  setFixedZoomDims: (fixedZoomW, fixedZoomH) => set({ fixedZoomW, fixedZoomH }),

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
  setBatchOpen: (batchOpen) => set({ batchOpen }),
  setCalibOpen: (calibOpen) => set({ calibOpen }),
  setMetaOpen: (metaOpen) => set({ metaOpen }),
  setPrefsOpen: (prefsOpen) => set({ prefsOpen }),
  setGalleryOpen: (galleryOpen) => set({ galleryOpen }),
  setStatus: (msg) => {
    logStatus(msg); // breadcrumb trail for the bug report
    set({ status: msg });
  },
}));
