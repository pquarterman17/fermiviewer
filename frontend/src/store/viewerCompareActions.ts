// Compare / side-by-side / named-group action slice for the viewer
// store — split from viewer.ts (repo-health #33, second pass). Verbatim
// action bodies; viewer.ts assembles the store and viewerState.ts owns
// the ViewerState contract these actions implement.

import type { StateCreator } from "zustand";

import {
  groupMembers as groupMembersOf,
  resizePanes,
  stepWithin,
} from "../lib/groups";
import { nextGroupId, paneCompareSet } from "./viewerSession";
import type { ViewerState } from "./viewerState";

type Set = Parameters<StateCreator<ViewerState>>[0];
type Get = Parameters<StateCreator<ViewerState>>[1];

export function createCompareActions(
  set: Set,
  get: Get,
): Pick<
  ViewerState,
  | "startCompare"
  | "exitCompare"
  | "setCompareMode"
  | "setCompareFlickerMs"
  | "setCompareAB"
  | "startSideBySide"
  | "setPaneImage"
  | "setPaneGroup"
  | "stepPane"
  | "setActivePane"
  | "setGrid"
  | "setSbsLinked"
  | "createGroup"
  | "renameGroup"
  | "deleteGroup"
  | "setGroupMembers"
> {
  return {
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
  };
}
