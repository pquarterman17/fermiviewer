// Measurement + ROI-manager action slice for the viewer store — split
// from viewer.ts (repo-health #33, second pass). Verbatim action bodies;
// viewer.ts assembles the store and viewerState.ts owns the ViewerState
// contract these actions implement.

import type { StateCreator } from "zustand";

import { nextMeasureId } from "./viewerSession";
import type { ViewerState } from "./viewerState";
import { UNDO_CAP, type Measure, type SavedRoi } from "./viewerTypes";

type Set = Parameters<StateCreator<ViewerState>>[0];
type Get = Parameters<StateCreator<ViewerState>>[1];

export function createMeasureActions(
  set: Set,
  get: Get,
): Pick<
  ViewerState,
  | "addMeasure"
  | "updateMeasure"
  | "removeMeasure"
  | "addHole"
  | "removeHole"
  | "deleteLastAnnotation"
  | "resetToOriginal"
  | "setMeasureText"
  | "setMeasureStyle"
  | "setMeasureFontSize"
  | "setMeasureDisplayUnit"
  | "setAllMeasureDisplayUnits"
  | "clearMeasures"
  | "setSelectedMeasure"
  | "setRoiStats"
  | "saveRoi"
  | "recallRoi"
  | "deleteRoi"
  | "seedSavedRois"
> {
  return {
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

    updateMeasure: (imageId, measureId, pts, holes) =>
      set((s) => ({
        measures: {
          ...s.measures,
          [imageId]: (s.measures[imageId] ?? []).map((m) =>
            m.id === measureId
              ? { ...m, pts, ...(holes !== undefined ? { holes } : {}) }
              : m,
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

    // ── draw a hole (plan item 4) ───────────────────────────────────────
    // The area math (lib/geometry polygonStatsWithHoles), the schema field
    // (Measure.holes) and the region-table reporting all shipped in item
    // 19; this is the gesture that actually populates the field. Which
    // host a ring attaches to is decided in pointerDecisions.ts
    // (findHoleHost) by the caller (MeasureCtxMenu) — this action just
    // performs the move, undoably.

    addHole: (imageId, hostId, childId) =>
      set((s) => {
        const list = s.measures[imageId] ?? [];
        const child = list.find((m) => m.id === childId);
        const host = list.find((m) => m.id === hostId);
        if (!child || !host || child.id === host.id) return {};
        if (child.kind !== "polygon" && child.kind !== "lasso") return {};
        return {
          measures: {
            ...s.measures,
            [imageId]: list
              .filter((m) => m.id !== childId)
              .map((m) =>
                m.id === hostId
                  ? { ...m, holes: [...(m.holes ?? []), child.pts] }
                  : m,
              ),
          },
          selectedMeasure:
            s.selectedMeasure === childId ? hostId : s.selectedMeasure,
          undoStack: [
            ...s.undoStack.slice(-UNDO_CAP),
            { t: "hole-add" as const, imageId, hostId, child },
          ],
          redoStack: [],
        };
      }),

    removeHole: (imageId, hostId, holeIndex) =>
      set((s) => {
        const list = s.measures[imageId] ?? [];
        const host = list.find((m) => m.id === hostId);
        const hole = host?.holes?.[holeIndex];
        if (!host || !hole) return {};
        const child: Measure = { id: nextMeasureId(), kind: "polygon", pts: hole };
        return {
          measures: {
            ...s.measures,
            [imageId]: list
              .map((m) =>
                m.id === hostId
                  ? {
                      ...m,
                      holes: (m.holes ?? []).filter((_, i) => i !== holeIndex),
                    }
                  : m,
              )
              .concat(child),
          },
          selectedMeasure: child.id,
          undoStack: [
            ...s.undoStack.slice(-UNDO_CAP),
            { t: "hole-remove" as const, imageId, hostId, child },
          ],
          redoStack: [],
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

    // ── display-unit override (measure display-units feature) ──────────
    // A DISPLAY preference, not a measurement edit: unlike the actions
    // above it never pushes an undo entry and never touches `pts`/
    // `holes` — same non-undoable idiom as setMeasureStyle/
    // setMeasureFontSize just above.

    setMeasureDisplayUnit: (imageId, measureId, unit) =>
      set((s) => ({
        measures: {
          ...s.measures,
          [imageId]: (s.measures[imageId] ?? []).map((m) =>
            m.id === measureId ? { ...m, displayUnit: unit } : m,
          ),
        },
      })),

    setAllMeasureDisplayUnits: (imageId, unit) =>
      set((s) => ({
        measures: {
          ...s.measures,
          [imageId]: (s.measures[imageId] ?? []).map((m) => ({
            ...m,
            displayUnit: unit,
          })),
        },
      })),

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
  };
}
