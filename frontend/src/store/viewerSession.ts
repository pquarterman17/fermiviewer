// Persistence + session restore machinery for the viewer store — split
// from viewer.ts (repo-health #33). Owns the localStorage keys/helpers,
// the module-level id counters (minted here, reseeded on session load so
// restored ids can never collide), image ingest, and the session slice
// that save/load round-trips.

import {
  isFourDMeta,
  type FourDMeta,
  type ImageMeta,
  type PersistedResultRecord,
  type ProjectRegions,
  type SessionClientState,
  type UnavailableImage,
} from "../lib/api";
import type { TiltSettings } from "../lib/geometry";
import {
  pruneGroups,
  resizePanes,
  type ComparePane,
  type ImageGroup,
} from "../lib/groups";
import { restoreRegionUi } from "../lib/regionWorkspace";
import { useBrowseScale } from "./browseScale";
import { applyHoleUndoEntry } from "./viewerHoleUndo";
import type { ViewerState } from "./viewerState";
import {
  DEFAULT_DISPLAY,
  type Display,
  type HistoryStep,
  type Measure,
  type OverlayStyle,
  type SavedRoi,
  type Theme,
  type UndoEntry,
  type View,
} from "./viewerTypes";

export const VIEWS_KEY = "fv_views";
export const OVERLAY_KEY = "fv_overlay";
export const THEME_KEY = "fv_theme";

/** Resolve the OS colour-scheme to a concrete theme. */
export function systemTheme(): Theme {
  return window.matchMedia?.("(prefers-color-scheme: light)").matches
    ? "light"
    : "dark";
}

export function initialTheme(): Theme {
  // explicit persisted choice wins; "system"/absent follow the OS (checklist N)
  const stored = localStorage.getItem(THEME_KEY);
  if (stored === "dark" || stored === "light") return stored;
  return systemTheme();
}

export function loadJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

/** Read one persisted preference with a fallback (lib/prefs.ts owns
 *  the dialog; this avoids an import cycle at store-init time). */
export function pref<T>(key: string, fallback: T): T {
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
export function writePref(key: string, value: unknown): void {
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

// ── module-level id counters ───────────────────────────────────────────
// Minted here and reseeded by sessionSlice on restore, so viewer.ts
// actions and session loads can never hand out a colliding id.

let historySeq = 0;
let measureSeq = 0;
/** Monotonic counter for stable, collision-free group ids across a session. */
let groupSeq = 0;

export function nextHistoryId(): number {
  return ++historySeq;
}

export function nextMeasureId(): string {
  return `m${++measureSeq}`;
}

export function nextGroupId(): string {
  return `g${++groupSeq}`;
}

/** The distinct, in-order image ids currently shown across the compare grid
 *  — used to keep compareSet (which drives Save/Copy of the comparison) in
 *  sync with the panes. */
export function paneCompareSet(panes: ComparePane[]): string[] {
  const seen = new Set<string>();
  const ids: string[] = [];
  for (const p of panes) {
    if (p.imageId && !seen.has(p.imageId)) {
      seen.add(p.imageId);
      ids.push(p.imageId);
    }
  }
  return ids;
}

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

/** Merge newly opened images into the library (shared by path + upload).
 *
 *  `metas` may include FourDMeta entries (a 4D-STEM file the server routed
 *  into its separate FourD store — see routes/images.py's `/session/open`);
 *  those are skipped here rather than added as a malformed image, since
 *  there's no render/measure pipeline for them yet. */
export function ingestImages(
  set: SetState,
  metas: (ImageMeta | FourDMeta)[],
): void {
  const images2D = metas.filter((m): m is ImageMeta => !isFourDMeta(m));
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
    for (const m of images2D) {
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
              id: nextHistoryId(),
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
    const last = images2D[images2D.length - 1];
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
export function applyUndoEntry(
  set: SetFull,
  e: UndoEntry,
  dir: "undo" | "redo",
): void {
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
              ? {
                  ...m,
                  pts: inverse ? e.before : e.after,
                  // holes-detach fix: only entries from a body-translate
                  // that actually had holes carry these — leave m.holes
                  // untouched for every other measure-move producer.
                  ...(e.beforeHoles !== undefined || e.afterHoles !== undefined
                    ? { holes: inverse ? e.beforeHoles : e.afterHoles }
                    : {}),
                }
              : m,
          ),
        },
      }));
      break;
    case "hole-add":
    case "hole-remove":
      // logic lives in viewerHoleUndo.ts — this case alone tipped the
      // module over the frontend size ratchet
      applyHoleUndoEntry(set, e, inverse);
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

/** The serializable slice of store state a saved session captures —
 *  shared by every save path (file + named workspace).
 *
 *  `browseScale` (plan item 11) lives in its OWN standalone store
 *  (store/browseScale.ts), not on `ViewerState` — it is read here rather
 *  than threaded in as a parameter, so every caller gets it for free. */
export function clientState(s: ViewerState): SessionClientState {
  const { locked, scale } = useBrowseScale.getState();
  return {
    order: s.order,
    activeId: s.activeId,
    views: s.views,
    display: s.display,
    measures: s.measures,
    overlay: s.overlay,
    savedRois: s.savedRois,
    regionUi: s.regionUi,
    imageGroups: s.imageGroups,
    sbsPanes: s.sbsPanes,
    sbsRows: s.sbsRows,
    sbsCols: s.sbsCols,
    browseScale: { locked, scale },
  };
}

/** Apply a loaded session's browse-scale lock to its own standalone store
 *  (plan item 11). Kept out of `sessionSlice`'s `Partial<ViewerState>`
 *  return on purpose — `browseScale` is deliberately not on `ViewerState` —
 *  so every load call site applies this alongside `sessionSlice`.
 *
 *  Additive and backward compatible: a project saved before this key
 *  existed (or one holding anything malformed) has no usable `browseScale`,
 *  so the lock simply comes back off rather than erroring. */
export function restoreBrowseScale(
  cs: SessionClientState | null | undefined,
): void {
  const raw = cs?.browseScale;
  const scale =
    typeof raw?.scale === "number" && Number.isFinite(raw.scale) && raw.scale > 0
      ? raw.scale
      : null;
  useBrowseScale.setState({ locked: raw?.locked === true && scale != null, scale });
}

/** Bump `current` past every numeric suffix found in `ids` matching `re`
 *  (captured in group 1). Used to re-seed measureSeq/groupSeq on session
 *  restore so a subsequent addMeasure/createGroup can never mint an id
 *  that collides with one just restored (duplicate React keys, double
 *  drag/delete on the wrong element). */
function reseedSeq(current: number, ids: Iterable<string>, re: RegExp): number {
  let max = current;
  for (const id of ids) {
    const m = re.exec(id);
    if (m) max = Math.max(max, Number(m[1]));
  }
  return max;
}

/** Build the store slice that a loaded session replaces — shared by
 *  openProject (arbitrary path) and loadWorkspaceNamed (config-dir
 *  workspace) so both restore identical state (status + currentWorkspace
 *  are added by each caller). */
export function sessionSlice(
  r: {
    images: ImageMeta[];
    client_state: SessionClientState | null;
    /** Images the project referenced but this machine could not find
     *  (ADR 0002 §4). Absent for callers that cannot produce any. */
    unavailable?: UnavailableImage[];
    /** Persisted project results; absent only for pre-1B test/mocked callers. */
    results?: PersistedResultRecord[];
    /** Canonical named-region section; absent for older mocked callers. */
    regions?: ProjectRegions;
  },
  fallbackOverlay: OverlayStyle,
): Partial<ViewerState> {
  const images: Record<string, ImageMeta> = {};
  for (const m of r.images) images[m.id] = m;
  const unavailable: Record<string, UnavailableImage> = {};
  for (const u of r.unavailable ?? []) unavailable[u.id] = u;
  const cs = r.client_state ?? {};
  const savedOrder = cs.order as string[] | undefined;
  const loadedIds = r.images.map((m) => m.id);
  // saved order filtered to what actually loaded; append any newcomers.
  // Placeholders are deliberately absent: `order` drives the stage, the card
  // list and arrow-key navigation, none of which can do anything with an
  // image that has no pixels. They render as their own library block instead.
  const order = (savedOrder?.filter((id) => id in images) ?? loadedIds).concat(
    loadedIds.filter((id) => !savedOrder?.includes(id)),
  );
  const activeId =
    typeof cs.activeId === "string" && cs.activeId in images
      ? cs.activeId
      : (order[0] ?? null);
  // groups: prune member ids to what actually loaded; drop groups left with
  // neither members nor a surviving descendant. Sample params/parent (and any
  // field a newer version added) ride through — see pruneGroups.
  //
  // A PLACEHOLDER COUNTS AS LOADED here. Pruning against `images` alone would
  // silently drop an unavailable image's sample membership, and the next save
  // would write that loss to the file — exactly the data destruction ADR 0002
  // §4 forbids. (The server keeps the manifest's own membership regardless;
  // this is what stops the client re-saving a pruned copy over it.)
  const rawGroups = (cs.imageGroups as ImageGroup[] | undefined) ?? [];
  const imageGroups: ImageGroup[] = pruneGroups(rawGroups, {
    ...images,
    ...unavailable,
  });
  const liveGroupIds = new Set(imageGroups.map((g) => g.id));
  // grid: restore shape, then prune each pane's image + group binding
  const sbsRows = Math.max(1, Math.round((cs.sbsRows as number) ?? 1));
  const sbsCols = Math.max(1, Math.round((cs.sbsCols as number) ?? 2));
  const rawPanes = (cs.sbsPanes as ComparePane[] | undefined) ?? [];
  const sbsPanes = resizePanes(
    rawPanes.map((p) => ({
      imageId: p?.imageId && p.imageId in images ? p.imageId : null,
      groupId: p?.groupId && liveGroupIds.has(p.groupId) ? p.groupId : null,
    })),
    sbsRows,
    sbsCols,
  );
  const measures = (cs.measures as Record<string, Measure[]>) ?? {};
  const loadedRegions = r.regions ?? { schema: 1 as const, classes: [], sets: [] };
  const regionUi = restoreRegionUi(cs.regionUi, loadedRegions);
  // re-seed the module id counters past whatever this session contains —
  // see reseedSeq above for why.
  measureSeq = reseedSeq(
    measureSeq,
    Object.values(measures).flatMap((list) => list.map((m) => m.id)),
    /^m(\d+)$/,
  );
  groupSeq = reseedSeq(
    groupSeq,
    imageGroups.map((g) => g.id),
    /^g(\d+)$/,
  );
  return {
    images,
    unavailable,
    persistedResults: r.results ?? [],
    regions: loadedRegions,
    regionUi,
    order,
    activeId,
    selected: activeId ? [activeId] : [],
    compareSet: null,
    selectedMeasure: null,
    selectedMulti: [],
    imageGroups,
    sbsPanes,
    sbsRows,
    sbsCols,
    sbsActive: 0,
    views: (cs.views as Record<string, View>) ?? {},
    display: (cs.display as Record<string, Display>) ?? {},
    measures,
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
