// closeImage teardown — split out of viewer.ts (W4 #22) both to buy that
// module back under the 500-line ceiling and to give the group prune a home
// where it can reuse lib/groups' rule instead of re-deriving one.
//
// Closing an image touches every per-image map in the store; keeping the
// whole teardown in one place is what makes it auditable that none of them
// leaks across an open/close-heavy session.

import type { StateCreator } from "zustand";

import { closeImage as apiClose } from "../lib/api";
import { pruneGroups } from "../lib/groups";
import { VIEWS_KEY } from "./viewerSession";
import type { ViewerState } from "./viewerState";

type Set = Parameters<StateCreator<ViewerState>>[0];

export function createCloseAction(set: Set): Pick<ViewerState, "closeImage"> {
  return {
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
        // Drop the closed image from every group's member list and prune the
        // groups that die with it — through pruneGroups, which keeps a group
        // that still has a live DESCENDANT. Filtering on `ids.length > 0`
        // here instead (as this did before W4 #22) deletes a project the
        // moment one of its samples empties, because a project's own `ids`
        // are empty by design: it holds its images through its samples.
        const imageGroups = pruneGroups(s.imageGroups, images);
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
  };
}
