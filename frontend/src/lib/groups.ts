// Pure helpers for named image groups + the N-pane compare grid. Kept out
// of the store so they can be unit-tested directly (and reused by the
// SideBySideStage / CompareInspector without re-deriving the rules).

/** A named, reusable set of images. `ids` is an ordered member list; it may
 *  hold ids that have since been closed — callers prune with groupMembers. */
export interface ImageGroup {
  id: string;
  name: string;
  ids: string[];
}

/** One cell of the compare grid. `imageId` is the image shown; `groupId`
 *  binds the cell to a named group so ◀▶/←→ step within that group. */
export interface ComparePane {
  imageId: string | null;
  groupId: string | null;
}

/** Resolve a group's live member list: the group's ids pruned to ones still
 *  open (present in `images`), preserving the group's order. When groupId is
 *  null / unknown / resolves to empty, fall back to the full `order` — this
 *  mirrors the MATLAB GroupModel.membersFor semantics (a pane with no group
 *  steps through every loaded image). */
export function groupMembers(
  groups: ImageGroup[],
  images: Record<string, unknown>,
  order: string[],
  groupId: string | null,
): string[] {
  if (groupId) {
    const g = groups.find((x) => x.id === groupId);
    if (g) {
      const live = g.ids.filter((id) => id in images);
      if (live.length > 0) return live;
    }
  }
  return order.filter((id) => id in images);
}

/** Step `current` within `members` by `delta` (wrapping). If `current` isn't
 *  in `members` (e.g. it was closed, or the bound group changed), snap to the
 *  first member. Returns null when there are no members at all. */
export function stepWithin(
  members: string[],
  current: string | null,
  delta: number,
): string | null {
  if (members.length === 0) return null;
  const i = current ? members.indexOf(current) : -1;
  if (i === -1) return members[0];
  const n = members.length;
  return members[((i + delta) % n + n) % n];
}

/** Grow or shrink the pane list to `rows*cols`, preserving existing panes
 *  (image + group bindings) by index; new cells start empty/unbound. */
export function resizePanes(
  panes: ComparePane[],
  rows: number,
  cols: number,
): ComparePane[] {
  const n = Math.max(1, Math.round(rows)) * Math.max(1, Math.round(cols));
  const out: ComparePane[] = [];
  for (let i = 0; i < n; i++) {
    out.push(panes[i] ?? { imageId: null, groupId: null });
  }
  return out;
}
