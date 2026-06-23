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
  /** colorbar tick count (overrides tickStep when set and > 0) */
  tickCount?: number;
  /** colorbar tick-label font size in screen px; undefined = 11 (default) */
  tickFontSize?: number;
}

export type ColorbarSide = "left" | "right" | "bottom";

export const DEFAULT_DISPLAY: Display = {
  lo: 0,
  hi: 1,
  gamma: 1,
  cmap: "gray",
  invert: false,
  transform: "linear",
};

/** One entry in an image's non-destructive edit history (design WS4d).
 *  Each step snapshots the FULL display state after the change, so a
 *  revert is just restoring that snapshot. `field` groups consecutive
 *  edits of the same control (a gamma drag coalesces into one step). */
export interface HistoryStep {
  id: number;
  label: string;
  field: string;
  display: Display;
}

let historySeq = 0;

/** Human label + coalescing field for a display change. Single-field
 *  patches get a specific label; the auto-window {lo,hi} pair and the
 *  reset patch are recognised so the card reads like the design example
 *  (Opened → Colormap → Auto contrast → Gamma). */
function describePatch(patch: Partial<Display>): { field: string; label: string } {
  const keys = Object.keys(patch);
  const has = (k: keyof Display) => k in patch;
  if (keys.length === 2 && has("lo") && has("hi"))
    return { field: "window", label: "Auto contrast" };
  if (keys.length > 1) return { field: "reset", label: "Reset display" };
  if (has("cmap")) return { field: "cmap", label: `Colormap → ${patch.cmap}` };
  if (has("gamma"))
    return { field: "gamma", label: `Gamma ${(patch.gamma ?? 1).toFixed(2)}` };
  if (has("invert"))
    return { field: "invert", label: `Invert ${patch.invert ? "on" : "off"}` };
  if (has("transform"))
    return { field: "transform", label: `Transform → ${patch.transform}` };
  if (has("tickStep")) return { field: "tickStep", label: "Tick step" };
  if (has("tickCount")) return { field: "tickCount", label: "Tick count" };
  if (has("tickFontSize")) return { field: "tickFontSize", label: "Tick font" };
  if (has("lo") || has("hi")) return { field: "window", label: "Contrast" };
  return { field: "adjust", label: "Adjust" };
}

/** One entry in the named-ROI list (ROI Manager, audit Tier-2 #5).
 *  Geometry is stored as normalized pts (same as Measure.pts) + the
 *  original MeasureKind so recall can re-create either roi or ellipse. */
export interface SavedRoi {
  id: string;
  name: string;
  kind: "roi" | "ellipse";
  pts: { x: number; y: number }[];
  /** ISO timestamp — shown in the manager list for provenance */
  createdAt: string;
}

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
  /** per-annotation font size override in screen px; undefined → global
   *  overlay size (audit #12).  Values outside [6, 120] are clamped. */
  fontSize?: number;
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
  size: "XS" | "S" | "M" | "L" | "XL" | "XXL";
  color: string;
  /** Measurement/annotation line thickness in screen px (non-selected). */
  lineWidth: number;
  endSymbol: EndSymbol;
}

/** On-screen label px for each overlay size bucket. Shared by the
 *  MeasureOverlay renderer AND the export pipeline so burned-in labels
 *  match what's on the stage. */
export const OVERLAY_FONT_PX: Record<OverlayStyle["size"], number> = {
  XS: 10,
  S: 13,
  M: 16,
  L: 20,
  XL: 26,
  XXL: 34,
};

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
  color: string | null;       // bar + label colour; null = "#ffffff" (audit #10)
  unitOverride: string | null; // force a display unit; null = auto (audit #10)
}

export type CaptureMode =
  | "none"
  | "zoom"
  | "fixed-zoom"
  | "box-profile"
  | "crop-save"
  | "calibrate"
  | "specnav" // click/drag the main image → drives the EELS/EDS spectrum
  | MeasureKind;
export type Theme = "dark" | "light";
/** Swappable accent scheme (kept in sync with lib/prefs Accent; no import
 *  to avoid an init-time cycle, same as Theme vs ThemeChoice). */
export type Accent = "violet" | "teal" | "ocean" | "amber" | "rose";
/** UI density — drives the spacing/row-height/font-size token block. */
export type Density = "compact" | "regular" | "comfy";
export type ListView = "thumbs" | "names";
export type CompareMode = "split" | "flicker" | "subtract" | "sidebyside";

/** Which side-by-side pane the keyboard / arrows currently drive. */
export type SbsPane = "L" | "R";
export type SelectGesture = "single" | "toggle" | "range";
/** Detected layer interfaces, surfaced on the stage by LayersOverlay. */
export interface LayersOverlayState {
  imageId: string;
  axis: "y" | "x";
  interfaces: number[];              // depth positions (image pixels)
  traces: (number[] | null)[];       // per-interface wavy edge depths (px)
}

export type ToolKind =
  | "eels"
  | "eds"
  | "diffraction"
  | "fftmask"
  | "pixels"
  | "structure"
  | "overlay"
  | "surface"
  | "layers";

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
    display: Record<string, Display>;
    history: Record<string, HistoryStep[]>;
    historyAt: Record<string, number>;
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
    const display = { ...s.display };
    const history = { ...s.history };
    const historyAt = { ...s.historyAt };
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
        // WS4d: seed the origin history step (the image's birth). Derived
        // images (filters/FFT) carry derived_from; everything else is Opened.
        if (!(m.id in history)) {
          history[m.id] = [
            {
              id: ++historySeq,
              field: "open",
              label: m.meta["derived_from"] ? "Derived" : "Opened",
              display: display[m.id] ?? DEFAULT_DISPLAY,
            },
          ];
          historyAt[m.id] = 0;
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
      history,
      historyAt,
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
  /** Flicker interval in ms (default 600 = ~1.7 Hz, matches MATLAB).
   *  Exposed as a user control (audit #15). */
  compareFlickerMs: number;
  /** Explicit A/B slot override: [indexA, indexB] into compareSet
   *  (null = cycle the full set, original behaviour).  Audit #15. */
  compareAB: [number, number] | null;
  // ── side-by-side compare (MATLAB-style independent panes) ──
  /** Image id shown in the left / right pane (compareMode "sidebyside"). */
  sbsLeft: string | null;
  sbsRight: string | null;
  /** Which pane the ←/→ keys + ◀▶ buttons drive; the other stays frozen. */
  sbsActive: SbsPane;
  /** Link zoom/pan across the two panes (default true; toggle to unlink). */
  sbsLinked: boolean;
  // monotonic counter bumped on every ingestDerived — a lineage signal that
  // lets views like Live FFT re-fetch when a new derived image is produced
  // without subscribing to the whole image map (Quick-Wins #7)
  derivedTick: number;
  // per-image view, persisted (localStorage "fv_views")
  views: Record<string, View>;
  // per-image display pipeline (window/gamma/colormap)
  display: Record<string, Display>;
  // WS4d: per-image non-destructive edit history + the current-step cursor
  history: Record<string, HistoryStep[]>;
  historyAt: Record<string, number>;
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
  /** Named saved ROIs per image — keyed by image id.  Persisted in session
   *  client_state["savedRois"] so save/load round-trips them (Tier-2 #5). */
  savedRois: Record<string, SavedRoi[]>;
  /** fixed-zoom dimensions in image pixels (A2 capture mode) */
  fixedZoomW: number;
  fixedZoomH: number;
  // tools
  captureMode: CaptureMode;
  // spectrum-navigation pixel (1-based [row, col]) picked on the main stage in
  // specnav mode; the EELS/EDS workshops watch it to drive their spectrum (#10)
  specnavPixel: [number, number] | null;
  layersOverlay: LayersOverlayState | null;
  layersEdit: boolean;                 // stage interface-editing mode
  layersEditReq: number[] | null;      // positions requested by a stage edit
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
  /** Whether the launch-folder Open dialog is showing. */
  folderOpen: boolean;
  /** The folder the app was launched from + its supported images, so the
   *  Open dialog can default there. null until fetched / when none set. */
  launchContext: { dir: string | null; files: { name: string; path: string }[] } | null;
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
  setCompareFlickerMs: (ms: number) => void;
  setCompareAB: (ab: [number, number] | null) => void;
  /** Enter side-by-side compare seeded from the current image (left =
   *  active, right = next in order). No pre-selection needed. */
  startSideBySide: () => void;
  /** Set a pane's image directly (e.g. dropdown pick) and focus it. */
  setSbsPane: (pane: SbsPane, id: string) => void;
  /** Step a pane through `order` by delta (wrapping) and focus it. */
  stepSbs: (pane: SbsPane, delta: 1 | -1) => void;
  setSbsActive: (pane: SbsPane) => void;
  setSbsLinked: (linked: boolean) => void;
  cycleImage: (dir: 1 | -1) => void;
  closeImage: (id: string) => Promise<void>;
  setView: (id: string, view: View) => void;
  setDisplay: (
    id: string,
    patch: Partial<Display>,
    opts?: { silent?: boolean },
  ) => void;
  ingestDerived: (metas: ImageMeta[]) => void;
  /** WS4d: jump the active image's display to a history step (revert or
   *  step forward); moves the cursor without dropping steps. */
  revertHistory: (id: string, index: number) => void;
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
  /** Remove the most recently added annotation/measure (audit #11). */
  deleteLastAnnotation: (imageId: string) => void;
  /** Switch the active image to the root ancestor of a derived chain,
   *  restoring the original un-filtered pixels (audit #11).  The server
   *  already holds every ancestor DataStruct for the session; this only
   *  updates the client's activeId pointer. */
  resetToOriginal: (imageId: string) => void;
  setMeasureText: (imageId: string, measureId: string, text: string) => void;
  setMeasureStyle: (
    imageId: string,
    measureId: string,
    patch: Partial<Pick<Measure, "color" | "labelDx" | "labelDy" | "endSymbol">>,
  ) => void;
  /** Set per-annotation font size override (audit #12); null clears it. */
  setMeasureFontSize: (imageId: string, measureId: string, size: number | null) => void;
  /** marquee multi-selection (shift-drag on the stage) */
  selectedMulti: string[];
  setSelectedMulti: (ids: string[]) => void;
  /** Remove all measures (or only the given kinds), undoably. */
  clearMeasures: (imageId: string, kinds: MeasureKind[] | null) => void;
  setSelectedMeasure: (id: string | null) => void;
  setRoiStats: (measureId: string, stats: RoiStats) => void;
  setCaptureMode: (mode: CaptureMode) => void;
  setSpecnavPixel: (p: [number, number] | null) => void;
  setLayersOverlay: (o: LayersOverlayState | null) => void;
  setLayersEdit: (b: boolean) => void;
  setLayersEditReq: (p: number[] | null) => void;
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
  setFolderOpen: (open: boolean) => void;
  setLaunchContext: (
    ctx: { dir: string | null; files: { name: string; path: string }[] } | null,
  ) => void;
  setStatus: (msg: string) => void;

  // ── ROI Manager (Tier-2 #5) ─────────────────────────────────────────
  /** Save the given measure (must be roi/ellipse kind) under `name` for
   *  the specified image.  Replaces an existing entry with the same name. */
  saveRoi: (imageId: string, name: string, roi: Pick<SavedRoi, "kind" | "pts">) => void;
  /** Re-create a saved ROI as the active measure+selection for an image. */
  recallRoi: (imageId: string, roiId: string) => void;
  /** Remove one named ROI from the list. */
  deleteRoi: (imageId: string, roiId: string) => void;
  /** Bulk-replace the saved-ROI list — used on session load. */
  seedSavedRois: (map: Record<string, SavedRoi[]>) => void;
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
    savedRois: s.savedRois,
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
    savedRois: (cs.savedRois as Record<string, SavedRoi[]>) ?? {},
    // a load is a fresh session: drop undo history + per-image state that
    // isn't part of the saved payload so it doesn't bleed across loads
    undoStack: [],
    redoStack: [],
    history: {},
    historyAt: {},
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
  compareFlickerMs: 600,
  compareAB: null,
  sbsLeft: null,
  sbsRight: null,
  sbsActive: "L",
  sbsLinked: true,
  derivedTick: 0,
  views: loadJson<Record<string, View>>(VIEWS_KEY, {}),
  display: {},
  history: {},
  historyAt: {},
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
  // merge defaults UNDER the persisted value so fields added later
  // (lineWidth) are present even on overlays saved before they existed
  overlay: {
    size: "L" as const,
    color: "#ffffff",
    lineWidth: 2.5,
    endSymbol: "bar" as const,
    ...loadJson<Partial<OverlayStyle>>(OVERLAY_KEY, {}),
  },
  scaleBars: {},
  tilts: {},
  stackFrames: {},
  savedRois: {},
  fixedZoomW: _pref("fixedZoomW", 256),
  fixedZoomH: _pref("fixedZoomH", 256),
  captureMode: "none",
  specnavPixel: null,
  layersOverlay: null,
  layersEdit: false,
  layersEditReq: null,
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
  folderOpen: false,
  launchContext: null,
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
      derivedTick: s.derivedTick + 1, // lineage signal (Live FFT, #7)
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
    // reset to the linked "split" mode so a fresh multi-image compare never
    // lands in a stale "sidebyside" left over from a prior session
    set({
      compareSet: ids,
      compareMode: "split",
      captureMode: "none",
      selectedMeasure: null,
      compareAB: null,
    });
  },

  exitCompare: () =>
    set({ compareSet: null, compareAB: null, compareMode: "split" }),
  setCompareMode: (compareMode) => {
    if (compareMode !== "sidebyside") {
      set({ compareMode });
      return;
    }
    // entering side-by-side: seed panes from existing sbs ids if still
    // valid, else the compareSet's first two, else active + next-in-order.
    // The `ok` guard also self-heals dangling ids left by a prior close.
    const s = get();
    const ok = (id: string | null): id is string => !!id && !!s.images[id];
    const cs = s.compareSet ?? [];
    const nextOf = (id: string | null): string | null => {
      if (s.order.length === 0) return id;
      const i = id ? s.order.indexOf(id) : -1;
      return s.order[(i + 1 + s.order.length) % s.order.length] ?? id;
    };
    const L = ok(s.sbsLeft) ? s.sbsLeft : (cs[0] ?? s.activeId ?? s.order[0] ?? null);
    const R =
      ok(s.sbsRight) && s.sbsRight !== L
        ? s.sbsRight
        : ((ok(cs[1]) ? cs[1] : null) ?? nextOf(L) ?? L);
    set({
      compareMode,
      sbsLeft: L,
      sbsRight: R,
      compareSet: L && R ? [L, R] : s.compareSet,
    });
  },
  setCompareFlickerMs: (ms) =>
    set({ compareFlickerMs: Math.max(100, Math.round(ms)) }),
  setCompareAB: (ab) => set({ compareAB: ab }),

  startSideBySide: () => {
    const s = get();
    if (s.order.length < 2) {
      s.setStatus("open at least 2 images to compare side-by-side");
      return;
    }
    const L = s.activeId ?? s.order[0];
    const i = s.order.indexOf(L);
    const R = s.order[(i + 1) % s.order.length] ?? L;
    set({
      compareMode: "sidebyside",
      compareSet: [L, R],
      sbsLeft: L,
      sbsRight: R,
      sbsActive: "L",
      captureMode: "none",
      selectedMeasure: null,
      compareAB: null,
    });
  },

  setSbsPane: (pane, id) => {
    const s = get();
    if (!s.images[id]) return;
    const L = pane === "L" ? id : s.sbsLeft;
    const R = pane === "R" ? id : s.sbsRight;
    set({
      sbsLeft: L,
      sbsRight: R,
      sbsActive: pane,
      compareSet: L && R ? [L, R] : s.compareSet,
    });
  },

  stepSbs: (pane, delta) => {
    const s = get();
    const cur = pane === "L" ? s.sbsLeft : s.sbsRight;
    if (!cur || s.order.length === 0) return;
    const n = s.order.length;
    const i = s.order.indexOf(cur);
    // pane's image no longer in order (e.g. closed) → reset to the first
    if (i === -1) {
      get().setSbsPane(pane, s.order[0]);
      return;
    }
    get().setSbsPane(pane, s.order[((i + delta) % n + n) % n]);
  },

  setSbsActive: (pane) => set({ sbsActive: pane }),
  setSbsLinked: (sbsLinked) => set({ sbsLinked }),

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
      // if the closed image sat in a side-by-side pane, drop the dangling ref
      // (the pane reseeds from `order` when compare is re-entered)
      const sbsLeft = s.sbsLeft === id ? null : s.sbsLeft;
      const sbsRight = s.sbsRight === id ? null : s.sbsRight;
      // drop the closed image's per-image state so these maps don't grow
      // unbounded across an open/close-heavy session (and evict its
      // persisted view from localStorage)
      const views = { ...s.views };
      delete views[id];
      const display = { ...s.display };
      delete display[id];
      const history = { ...s.history };
      delete history[id];
      const historyAt = { ...s.historyAt };
      delete historyAt[id];
      const scaleBars = { ...s.scaleBars };
      delete scaleBars[id];
      const tilts = { ...s.tilts };
      delete tilts[id];
      const stackFrames = { ...s.stackFrames };
      delete stackFrames[id];
      const roiStats = { ...s.roiStats };
      for (const m of closed) delete roiStats[m.id];
      const savedRois = { ...s.savedRois };
      delete savedRois[id];
      localStorage.setItem(VIEWS_KEY, JSON.stringify(views));
      return {
        images,
        order,
        measures,
        activeId,
        selected: s.selected.filter((x) => x !== id),
        compareSet: compareSet && compareSet.length >= 2 ? compareSet : null,
        sbsLeft,
        sbsRight,
        views,
        display,
        history,
        historyAt,
        scaleBars,
        tilts,
        stackFrames,
        roiStats,
        savedRois,
      };
    });
  },

  setView: (id, view) => {
    const views = { ...get().views, [id]: view };
    localStorage.setItem(VIEWS_KEY, JSON.stringify(views));
    set({ views });
  },

  setDisplay: (id, patch, opts) =>
    set((s) => {
      const next = { ...(s.display[id] ?? DEFAULT_DISPLAY), ...patch };
      const display = { ...s.display, [id]: next };
      const steps = s.history[id];
      // silent seeds (Stage's one-time DM-window load) fold into the
      // current step's snapshot instead of logging a spurious "Contrast"
      if (opts?.silent) {
        if (!steps?.length) return { display };
        const at = s.historyAt[id] ?? steps.length - 1;
        const folded = steps.map((st, i) =>
          i === at ? { ...st, display: next } : st,
        );
        return { display, history: { ...s.history, [id]: folded } };
      }
      const { field, label } = describePatch(patch);
      const at = s.historyAt[id] ?? (steps ? steps.length - 1 : -1);
      // truncate any steps "ahead" of the cursor (edit after a revert)
      const base = (steps ?? []).slice(0, at + 1);
      const last = base[base.length - 1];
      const log =
        last && last.field === field && field !== "open"
          ? // coalesce consecutive edits of the same control into one step
            [...base.slice(0, -1), { ...last, label, display: next }]
          : [...base, { id: ++historySeq, field, label, display: next }];
      return {
        display,
        history: { ...s.history, [id]: log },
        historyAt: { ...s.historyAt, [id]: log.length - 1 },
      };
    }),

  revertHistory: (id, index) =>
    set((s) => {
      const steps = s.history[id];
      if (!steps || index < 0 || index >= steps.length) return {};
      return {
        display: { ...s.display, [id]: steps[index].display },
        historyAt: { ...s.historyAt, [id]: index },
      };
    }),

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

  deleteLastAnnotation: (imageId) => {
    const s = get();
    const list = s.measures[imageId] ?? [];
    if (list.length === 0) return;
    const last = list[list.length - 1];
    s.removeMeasure(imageId, last.id);
  },

  resetToOriginal: (imageId) => {
    // Walk the derived_from chain to find the root ancestor, then activate it.
    // Every ancestor DataStruct is server-resident for the life of the session;
    // switching activeId is all that is needed — no network reload.
    const s = get();
    let current = imageId;
    // Guard: at most as many hops as images in the library (cycle-proof)
    for (let i = 0; i < Object.keys(s.images).length; i++) {
      const parent = s.images[current]?.meta["derived_from"];
      if (!parent || typeof parent !== "string" || !(parent in s.images)) break;
      current = parent;
    }
    if (current !== imageId) s.setActive(current);
  },

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

  setMeasureFontSize: (imageId, measureId, size) =>
    set((s) => ({
      measures: {
        ...s.measures,
        [imageId]: (s.measures[imageId] ?? []).map((m) =>
          m.id === measureId
            ? { ...m, fontSize: size == null ? undefined : Math.min(120, Math.max(6, size)) }
            : m,
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

  setCaptureMode: (mode) =>
    // leaving specnav clears the picked pixel so a stale marker doesn't linger
    set(mode === "specnav" ? { captureMode: mode } : { captureMode: mode, specnavPixel: null }),
  setSpecnavPixel: (specnavPixel) => set({ specnavPixel }),
  setLayersOverlay: (layersOverlay) => set({ layersOverlay }),
  setLayersEdit: (layersEdit) => set({ layersEdit }),
  setLayersEditReq: (layersEditReq) => set({ layersEditReq }),
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
        color: null, unitOverride: null,
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
  setFolderOpen: (folderOpen) => set({ folderOpen }),
  setLaunchContext: (launchContext) => set({ launchContext }),
  setStatus: (msg) => {
    logStatus(msg); // breadcrumb trail for the bug report
    set({ status: msg });
  },

  // ── ROI Manager (Tier-2 #5) ─────────────────────────────────────────

  saveRoi: (imageId, name, roi) => {
    const id = `sr${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
    const entry: SavedRoi = {
      id,
      name: name.trim() || "ROI",
      kind: roi.kind,
      pts: roi.pts,
      createdAt: new Date().toISOString(),
    };
    set((s) => {
      const existing = s.savedRois[imageId] ?? [];
      // replace if same name exists so re-saving a tweaked geometry is clean
      const filtered = existing.filter((r) => r.name !== entry.name);
      return {
        savedRois: {
          ...s.savedRois,
          [imageId]: [...filtered, entry],
        },
      };
    });
  },

  recallRoi: (imageId, roiId) => {
    const s = get();
    const list = s.savedRois[imageId] ?? [];
    const saved = list.find((r) => r.id === roiId);
    if (!saved) return;
    // re-create as the active measure (addMeasure handles id/undo)
    get().addMeasure(imageId, { kind: saved.kind, pts: saved.pts });
  },

  deleteRoi: (imageId, roiId) =>
    set((s) => ({
      savedRois: {
        ...s.savedRois,
        [imageId]: (s.savedRois[imageId] ?? []).filter((r) => r.id !== roiId),
      },
    })),

  seedSavedRois: (map) => set({ savedRois: map }),
}));
