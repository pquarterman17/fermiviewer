// Single Zustand store — port of the prototype's useFermiViewer() hook
// (handoff §6). Phase 2: display pipeline, measurements, overlay style,
// command-palette / shortcuts / radial chrome.
//
// Decomposed (repo-health #33): the types/constants live in
// viewerTypes.ts, the ViewerState contract in viewerState.ts, and the
// persistence + session-restore machinery in viewerSession.ts. This
// module holds the store implementation and re-exports the public
// surface so call sites keep importing from "store/viewer".

import { create } from "zustand";

import {
  closeImage as apiClose,
  loadSession,
  loadWorkspaceNamed as apiLoadWorkspaceNamed,
  openSession,
  saveSession,
  saveWorkspaceNamed as apiSaveWorkspaceNamed,
  uploadFiles,
} from "../lib/api";
import { logStatus } from "../lib/errlog";
import {
  groupMembers as groupMembersOf,
  resizePanes,
  stepWithin,
} from "../lib/groups";
import type { ViewerState } from "./viewerState";
import {
  applyUndoEntry,
  clientState,
  ingestImages,
  initialTheme,
  loadJson,
  nextGroupId,
  nextHistoryId,
  nextMeasureId,
  OVERLAY_KEY,
  paneCompareSet,
  pref,
  sessionSlice,
  systemTheme,
  THEME_KEY,
  VIEWS_KEY,
  writePref,
} from "./viewerSession";
import {
  DEFAULT_DISPLAY,
  describePatch,
  UNDO_CAP,
  type Accent,
  type ColorbarSide,
  type Density,
  type OverlayStyle,
  type SavedRoi,
  type Theme,
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
  accent: (() => {
    const a = pref<Accent>("accent", "violet");
    document.documentElement.setAttribute("data-accent", a);
    return a;
  })(),
  density: (() => {
    const d = pref<Density>("density", "regular");
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
  fixedZoomW: pref("fixedZoomW", 256),
  fixedZoomH: pref("fixedZoomH", 256),
  captureMode: "none",
  specnavPixel: null,
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
  minimap: pref("minimap", true),
  colorbar: pref("colorbarOnByDefault", false),
  colorbarSide: pref<ColorbarSide>("colorbarSide", "right"),
  scaleBarVisible: pref("scaleBarVisible", true),
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

  // current client state as the serializable session payload
  saveWorkspace: async (path) => {
    const s = get();
    const r = await saveSession(path, clientState(s));
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
    const r = await apiSaveWorkspaceNamed(name, clientState(get()));
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
    // entering side-by-side: seed any empty panes (or panes whose image was
    // closed) from the compareSet, then the active image + following order.
    // Existing valid pane images + group bindings are preserved.
    const s = get();
    const ok = (id: string | null): id is string => !!id && !!s.images[id];
    const cs = (s.compareSet ?? []).filter(ok);
    const nextOf = (id: string | null): string | null => {
      if (s.order.length === 0) return id;
      const i = id ? s.order.indexOf(id) : -1;
      return s.order[(i + 1 + s.order.length) % s.order.length] ?? id;
    };
    let seed = 0;
    let prev: string | null = null;
    const sbsPanes = s.sbsPanes.map((p) => {
      if (ok(p.imageId)) {
        prev = p.imageId;
        return p;
      }
      // fill from compareSet first, then chase the order after the last image
      const id =
        cs[seed++] ?? nextOf(prev ?? s.activeId ?? s.order[0] ?? null);
      prev = id;
      return { ...p, imageId: ok(id) ? id : p.imageId };
    });
    set({ compareMode, sbsPanes, compareSet: paneCompareSet(sbsPanes) });
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
    // seed each pane in turn from its bound group (or the full order),
    // starting at the active image, advancing through the member list.
    const first = s.activeId ?? s.order[0];
    const sbsPanes = s.sbsPanes.map((p, i) => {
      const members = groupMembersOf(s.imageGroups, s.images, s.order, p.groupId);
      const start = members.indexOf(first);
      const base = start >= 0 ? start : 0;
      const id = members[(base + i) % members.length] ?? first;
      return { ...p, imageId: id };
    });
    set({
      compareMode: "sidebyside",
      sbsPanes,
      compareSet: paneCompareSet(sbsPanes),
      sbsActive: 0,
      captureMode: "none",
      selectedMeasure: null,
      compareAB: null,
    });
  },

  setPaneImage: (idx, id) => {
    const s = get();
    if (!s.images[id] || idx < 0 || idx >= s.sbsPanes.length) return;
    const sbsPanes = s.sbsPanes.map((p, i) =>
      i === idx ? { ...p, imageId: id } : p,
    );
    set({ sbsPanes, sbsActive: idx, compareSet: paneCompareSet(sbsPanes) });
  },

  setPaneGroup: (idx, groupId) => {
    const s = get();
    if (idx < 0 || idx >= s.sbsPanes.length) return;
    const members = groupMembersOf(s.imageGroups, s.images, s.order, groupId);
    const sbsPanes = s.sbsPanes.map((p, i) => {
      if (i !== idx) return p;
      // keep the current image if it's still a member, else snap to the first
      const imageId =
        p.imageId && members.includes(p.imageId)
          ? p.imageId
          : (members[0] ?? p.imageId);
      return { imageId, groupId };
    });
    set({ sbsPanes, sbsActive: idx, compareSet: paneCompareSet(sbsPanes) });
  },

  stepPane: (idx, delta) => {
    const s = get();
    const pane = s.sbsPanes[idx];
    if (!pane) return;
    const members = groupMembersOf(s.imageGroups, s.images, s.order, pane.groupId);
    const next = stepWithin(members, pane.imageId, delta);
    if (!next) return;
    get().setPaneImage(idx, next);
  },

  setActivePane: (idx) => {
    const s = get();
    if (idx < 0 || idx >= s.sbsPanes.length) return;
    set({ sbsActive: idx });
  },

  setGrid: (rows, cols) => {
    const s = get();
    const r = Math.max(1, Math.round(rows));
    const c = Math.max(1, Math.round(cols));
    const sbsPanes = resizePanes(s.sbsPanes, r, c);
    // seed any freshly-added empty panes so the grid is never blank on grow:
    // step one past the previous pane's image within the new pane's group
    const ok = (id: string | null | undefined): id is string =>
      !!id && !!s.images[id];
    let prev: string | null =
      [...s.sbsPanes].reverse().find((p) => ok(p.imageId))?.imageId ??
      s.activeId ??
      s.order[0] ??
      null;
    for (let i = 0; i < sbsPanes.length; i++) {
      const cur = sbsPanes[i].imageId;
      if (ok(cur)) {
        prev = cur;
        continue;
      }
      const members = groupMembersOf(
        s.imageGroups,
        s.images,
        s.order,
        sbsPanes[i].groupId,
      );
      const next: string | null = stepWithin(members, prev, 1);
      if (ok(next)) {
        sbsPanes[i] = { ...sbsPanes[i], imageId: next };
        prev = next;
      }
    }
    const sbsActive = Math.min(s.sbsActive, sbsPanes.length - 1);
    set({
      sbsRows: r,
      sbsCols: c,
      sbsPanes,
      sbsActive,
      compareSet: paneCompareSet(sbsPanes),
    });
  },

  setSbsLinked: (sbsLinked) => set({ sbsLinked }),

  // ── named image groups ────────────────────────────────────────────────
  createGroup: (ids, name) => {
    const s = get();
    const members = ids.filter((id) => id in s.images);
    if (members.length === 0) {
      s.setStatus("select at least one image to make a group");
      return;
    }
    const id = nextGroupId();
    const groupName = name?.trim() || `Group ${s.imageGroups.length + 1}`;
    set({
      imageGroups: [...s.imageGroups, { id, name: groupName, ids: members }],
    });
    s.setStatus(`group "${groupName}" created (${members.length})`);
  },

  renameGroup: (id, name) =>
    set((s) => ({
      imageGroups: s.imageGroups.map((g) =>
        g.id === id ? { ...g, name: name.trim() || g.name } : g,
      ),
    })),

  deleteGroup: (id) =>
    set((s) => ({
      imageGroups: s.imageGroups.filter((g) => g.id !== id),
      // unbind the deleted group from every pane (image stays put)
      sbsPanes: s.sbsPanes.map((p) =>
        p.groupId === id ? { ...p, groupId: null } : p,
      ),
    })),

  setGroupMembers: (id, ids) =>
    set((s) => ({
      imageGroups: s.imageGroups.map((g) =>
        g.id === id ? { ...g, ids: ids.filter((x) => x in s.images) } : g,
      ),
    })),

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
      // if the closed image sat in any compare pane, drop the dangling ref
      // (the pane reseeds from its group/order when compare is re-entered)
      const sbsPanes = s.sbsPanes.map((p) =>
        p.imageId === id ? { ...p, imageId: null } : p,
      );
      // drop the closed image from every group's member list; prune groups
      // that become empty, and unbind those from any pane that referenced them
      const imageGroups = s.imageGroups
        .map((g) => ({ ...g, ids: g.ids.filter((m) => m !== id) }))
        .filter((g) => g.ids.length > 0);
      const liveGroupIds = new Set(imageGroups.map((g) => g.id));
      const sbsPanesPruned = sbsPanes.map((p) =>
        p.groupId && !liveGroupIds.has(p.groupId) ? { ...p, groupId: null } : p,
      );
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
        sbsPanes: sbsPanesPruned,
        imageGroups,
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

  addMeasure: (imageId, m) => {
    const id = nextMeasureId();
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
