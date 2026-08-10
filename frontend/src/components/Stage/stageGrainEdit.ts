// Grain-map click editing for useStagePointers.ts (MAIN_PLAN item 1) — the
// merge/split gesture on a grain-label map, split out so the hook keeps
// only the branch that routes to it. grainClickAction is the pure decision
// (which op, on which pixels, or "remember this pick"); runGrainEdit is the
// round-trip that applies it, taking activeId and setStatus explicitly
// instead of closing over component state, the same shape as
// stageFinalizers.ts. Bodies moved verbatim.

import { grainsEdit } from "../../lib/api";
import type { Size } from "../../lib/geometry";
import { replaceCrossSectionGrainsAfterEdit } from "../../store/crossSection";
import { useViewer } from "../../store/viewer";
import type { Pt } from "./stageUtils";

/** Either an edit to run now, or the first half of a merge to remember. */
export type GrainAction =
  | { kind: "edit"; op: "merge" | "split"; points: [number, number][] }
  | { kind: "pick"; at: Pt };

/** What a plain click on a grain-label map means. Split edits the grain
 *  under the cursor immediately; merge needs two grains, so the first
 *  click only records a pick and the second runs the edit. The click snaps
 *  to a valid 0-based pixel index — a click at the exact w/h edge would
 *  otherwise be out of bounds server-side (→ 422 on a real click). */
export function grainClickAction(
  ip: Pt,
  imgSize: Size,
  mode: "merge" | "split",
  pick: Pt | null,
): GrainAction {
  const cp = {
    x: Math.min(imgSize.w - 1, Math.max(0, Math.floor(ip.x))),
    y: Math.min(imgSize.h - 1, Math.max(0, Math.floor(ip.y))),
  };
  if (mode === "split") {
    return { kind: "edit", op: "split", points: [[cp.x, cp.y]] };
  }
  if (pick) {
    return {
      kind: "edit",
      op: "merge",
      points: [
        [pick.x, pick.y],
        [cp.x, cp.y],
      ],
    };
  }
  return { kind: "pick", at: cp };
}

/** Run a grain merge/split and fold the result back in: the new label map
 *  is ingested as a derived image and the cross-section grain list is
 *  refreshed. The active image follows the edit only if the user is still
 *  on the image it started from, so a slow response cannot hijack a
 *  navigation (same guard as stageFinalizers.ts). */
export function runGrainEdit(
  activeId: string | null,
  op: "merge" | "split",
  points: [number, number][],
  setStatus: (msg: string) => void,
): void {
  if (!activeId) return;
  const startId = activeId;
  setStatus(op === "merge" ? "merging grains…" : "splitting grain…");
  grainsEdit(startId, op, points)
    .then((r) => {
      const s = useViewer.getState();
      s.ingestDerived([r.labels]);
      replaceCrossSectionGrainsAfterEdit(r);
      if (s.activeId === startId) s.setActive(r.labels.id);
      setStatus(
        `${r.n_grains} grains` +
          (r.astm_grain_size != null
            ? ` · ASTM G ${r.astm_grain_size.toFixed(1)}`
            : ""),
      );
    })
    .catch((e: Error) => setStatus(`grain edit: ${e.message}`));
}
