// applyUndoEntry's "hole-add"/"hole-remove" cases (plan item 4 — DRAW a
// hole), split out of viewerSession.ts to keep that module under the
// frontend module ratchet. Same "pure state surgery" contract as the
// switch case it replaces — never calls the public store actions
// (addHole/removeHole), so there is no re-push loop onto undoStack.

import type { ViewerState } from "./viewerState";
import type { UndoEntry } from "./viewerTypes";

type SetFull = (fn: (s: ViewerState) => Partial<ViewerState>) => void;

/** Apply one "hole-add"/"hole-remove" undo entry. "hole-add"'s forward
 *  (redo) direction moves the ring INTO host.holes; "hole-remove"'s
 *  forward direction moves a ring OUT of host.holes — `inverse` flips
 *  whichever one this entry represents, same (e.t === X) === inverse
 *  trick applyUndoEntry uses for measure-add/measure-del. */
export function applyHoleUndoEntry(
  set: SetFull,
  e: Extract<UndoEntry, { t: "hole-add" | "hole-remove" }>,
  inverse: boolean,
): void {
  const doHole = e.t === "hole-add" ? !inverse : inverse;
  if (doHole) {
    set((s) => ({
      measures: {
        ...s.measures,
        [e.imageId]: (s.measures[e.imageId] ?? [])
          .filter((m) => m.id !== e.child.id)
          .map((m) =>
            m.id === e.hostId
              ? { ...m, holes: [...(m.holes ?? []), e.child.pts] }
              : m,
          ),
      },
      selectedMeasure:
        s.selectedMeasure === e.child.id ? e.hostId : s.selectedMeasure,
    }));
  } else {
    set((s) => ({
      measures: {
        ...s.measures,
        [e.imageId]: (s.measures[e.imageId] ?? [])
          .map((m) =>
            m.id === e.hostId
              ? {
                  ...m,
                  holes: (m.holes ?? []).filter((h) => h !== e.child.pts),
                }
              : m,
          )
          .concat(e.child),
      },
    }));
  }
}
