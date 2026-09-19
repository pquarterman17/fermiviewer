// The undo/redo reducer: applying one `UndoEntry` in either direction.
//
// Split from viewerSession.ts when a new entry pushed that module past the
// 500-line guard, along a seam that was already there: everything here is
// pure state surgery for one history step, and nothing here restores or
// persists a session.
//
// It never calls the public actions — those push their own undo entries,
// which would loop.

import type { ViewerState } from "./viewerState";
import { applyHoleUndoEntry } from "./viewerHoleUndo";
import type { UndoEntry } from "./viewerTypes";

type SetFull = (fn: (s: ViewerState) => Partial<ViewerState>) => void;

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
    case "measure-width":
      set((s) => ({
        measures: {
          ...s.measures,
          [e.imageId]: (s.measures[e.imageId] ?? []).map((m) =>
            m.id === e.measureId
              ? { ...m, width: inverse ? e.before : e.after }
              : m,
          ),
        },
      }));
      break;
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
