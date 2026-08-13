// Single Zustand store — port of the prototype's useFermiViewer() hook
// (handoff §6). Phase 2: display pipeline, measurements, overlay style,
// command-palette / shortcuts / radial chrome.
//
// Decomposed (repo-health #33): the types/constants live in
// viewerTypes.ts, the ViewerState contract in viewerState.ts, and the
// persistence + session-restore machinery in viewerSession.ts. This
// module holds the store implementation and re-exports the public
// surface so call sites keep importing from "store/viewer".
//
// Further slices (W4 #22): viewerCloseImage.ts owns the close teardown and
// viewerChromeActions.ts the theme/accent/density/panel preferences.

import { create } from "zustand";

import {
  loadWorkspaceNamed as apiLoadWorkspaceNamed,
  openSession,
  saveWorkspaceNamed as apiSaveWorkspaceNamed,
  uploadFiles,
} from "../lib/api";
import { logStatus } from "../lib/errlog";
import { createChromeActions, initialChrome } from "./viewerChromeActions";
import { createCloseAction } from "./viewerCloseImage";
import { createCompareActions } from "./viewerCompareActions";
import { createMeasureActions } from "./viewerMeasureActions";
import { createProjectActions } from "./viewerProjectActions";
import type { ViewerState } from "./viewerState";
import {
  applyUndoEntry,
  clientState,
  ingestImages,
  initialTheme,
  loadJson,
  nextHistoryId,
  OVERLAY_KEY,
  pref,
  restoreBrowseScale,
  sessionSlice,
  VIEWS_KEY,
  writePref,
} from "./viewerSession";
import {
  DEFAULT_DISPLAY,
  describePatch,
  UNDO_CAP,
  type OverlayStyle,
  type View,
} from "./viewerTypes";

export * from "./viewerTypes";
export type { ViewerState } from "./viewerState";
export type { TiltSettings } from "../lib/geometry";
export type { ComparePane, ImageGroup } from "../lib/groups";

export const useViewer = create<ViewerState>((set, get) => ({
  order: [],
  activeId: null,
  images: {},
  unavailable: {},
  selected: [],
  listView: "thumbs",
  compareSet: null,
  compareMode: "split",
  compareFlickerMs: 600,
  compareAB: null,
  sbsPanes: [
    { imageId: null, groupId: null },
    { imageId: null, groupId: null },
  ],
  sbsRows: 1,
  sbsCols: 2,
  sbsActive: 0,
  sbsLinked: true,
  imageGroups: [],
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
  ...initialChrome(),
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
  fixedZoomW: pref("fixedZoomW", 256),
  fixedZoomH: pref("fixedZoomH", 256),
  captureMode: "none",
  specnavPixel: null,
  fourdNavPixel: null,
  layersOverlay: null,
  layersEdit: false,
  layersEditReq: null,
  layersFocusReq: null,
  panTool: false,
  profileWidth: pref("profileWidth", 1),
  profileReduce: pref<"mean" | "sum">("profileReduce", "mean"),
  toolsLayout: pref<"cards" | "unified">(
    "toolsLayout",
    localStorage.getItem("fv_tools_layout") === "unified" ? "unified" : "cards",
  ),
  leftCol: false,
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
  currentProject: null,

  openPaths: async (paths) => {
    ingestImages(set, await openSession(paths));
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
    ingestImages(set, await uploadFiles(files));
  },

  /** Register derived/analysis result images in the library. */
  ingest: (metas) => ingestImages(set, metas),

  /** Like ingest, but records each image on the undo stack (used by
   *  single-result operations: filters, transforms, FFT masks…). */
  ingestDerived: (metas) => {
    ingestImages(set, metas);
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

  // Save Project / Export Project Bundle / Open Project… / Locate folder…
  ...createProjectActions(set, get),

  saveWorkspaceNamed: async (name) => {
    const r = await apiSaveWorkspaceNamed(name, clientState(get()));
    set({
      currentWorkspace: { slug: r.slug, name: r.name },
      status: `saved workspace “${r.name}” · ${r.n_images} images`,
    });
  },

  loadWorkspaceNamed: async (slug) => {
    const r = await apiLoadWorkspaceNamed(slug);
    // a workspace is a light-mode project, so its sources can be missing too
    const missing = r.unavailable.length
      ? ` · ${r.unavailable.length} unavailable — File ▸ Locate Data Folder…`
      : "";
    restoreBrowseScale(r.client_state);
    set({
      ...sessionSlice(r, get().overlay),
      currentWorkspace: { slug, name: r.name },
      currentProject: r.project.path
        ? { path: r.project.path, name: r.project.name }
        : null,
      status: `opened workspace “${r.name}” · ${r.images.length} images${missing}`,
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

  // ── compare / side-by-side / named groups (viewerCompareActions.ts) ──
  ...createCompareActions(set, get),

  cycleImage: (dir) => {
    const { order, activeId } = get();
    if (order.length === 0) return;
    const i = activeId ? order.indexOf(activeId) : 0;
    const next = order[(i + dir + order.length) % order.length];
    set({ activeId: next, selected: [next], selectedMeasure: null });
  },

  // ── image-close teardown (viewerCloseImage.ts) ────────────────────────
  ...createCloseAction(set),

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
          : [...base, { id: nextHistoryId(), field, label, display: next }];
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

  // ── measurements + ROI manager (viewerMeasureActions.ts) ──────────────
  ...createMeasureActions(set, get),

  selectedMulti: [],
  setSelectedMulti: (selectedMulti) => set({ selectedMulti }),

  setCaptureMode: (mode) =>
    // leaving specnav/fourdnav clears its picked pixel so a stale marker
    // doesn't linger; entering either keeps a pixel already picked (e.g. a
    // fresh pick from just before the mode switch landed).
    set({
      captureMode: mode,
      ...(mode === "specnav" ? {} : { specnavPixel: null }),
      ...(mode === "fourdnav" ? {} : { fourdNavPixel: null }),
    }),
  setSpecnavPixel: (specnavPixel) => set({ specnavPixel }),
  setFourdNavPixel: (fourdNavPixel) => set({ fourdNavPixel }),
  setLayersOverlay: (layersOverlay) => set({ layersOverlay }),
  setLayersEdit: (layersEdit) => set({ layersEdit }),
  setLayersEditReq: (layersEditReq) => set({ layersEditReq }),
  setLayersFocusReq: (layersFocusReq) => set({ layersFocusReq }),
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

  // ── theme / accent / density / panel chrome (viewerChromeActions.ts) ──
  ...createChromeActions(set, get),

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
}));
