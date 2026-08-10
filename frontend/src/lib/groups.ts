// Pure helpers for named image groups + the N-pane compare grid. Kept out
// of the store so they can be unit-tested directly (and reused by the
// SideBySideStage / CompareInspector without re-deriving the rules).

/** One named experimental parameter on a sample. `value` is numeric for
 *  anything to be plotted against, string/boolean for categorical; `unit` is
 *  the physical unit (`degC`, `nm`, `sccm`), null/absent when dimensionless
 *  or categorical. Mirrors a `samples[].params[<name>]` entry of the project
 *  manifest (docs/schema/fvp-v2.schema.json). */
export interface GroupParam {
  value: number | string | boolean;
  unit?: string | null;
}

/** A sample's parameters, keyed by parameter name. */
export type GroupParams = Record<string, GroupParam>;

/** A named, reusable set of images — and, with `params`/`parent` set, a
 *  sample or a project. There is no separate grouping mechanism: a sample IS
 *  an ImageGroup, which is why the compare grid can already step through one
 *  (see ADR 0002 §5).
 *
 *  `ids` is an ordered member list; it may hold ids that have since been
 *  closed — callers prune with groupMembers. An image may sit in more than
 *  one group.
 *
 *  Maps 1:1 onto a manifest `samples[]` entry: `ids` is serialised as
 *  `image_ids`, every other field keeps its name. */
export interface ImageGroup {
  id: string;
  name: string;
  ids: string[];
  /** Parent group id, giving project → sample nesting. Null/absent for a
   *  root. Cycles are invalid — the store rejects them via wouldCycle, and
   *  pruneGroups breaks any that reach us from a file. */
  parent?: string | null;
  /** Named experimental parameters, present on samples that carry them. */
  params?: GroupParams;
  /** Display colour in sections, panes and plots; null/absent = derive one. */
  color?: string | null;
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

// ── sample / project nesting ────────────────────────────────────────────
// The helpers below are pure and cycle-safe (a corrupt or hand-edited
// manifest cannot hang the UI). They build fresh arrays, so call them in a
// component's render body from the `imageGroups` state array — never inside
// a zustand selector, which must return a stable snapshot.

const parentOf = (g: ImageGroup): string | null => g.parent ?? null;

const indexById = (groups: ImageGroup[]): Map<string, ImageGroup> =>
  new Map(groups.map((g) => [g.id, g]));

/** A group's direct children, in `groups` order. Pass `null` to enumerate the
 *  roots — every group whose parent is null or absent. Because the store
 *  never stores a parent that doesn't resolve (and pruneGroups clears any
 *  that arrive from a file), the roots plus a recursive walk reach every
 *  group. */
export function groupChildren(
  groups: ImageGroup[],
  parentId: string | null,
): ImageGroup[] {
  return groups.filter((g) => parentOf(g) === parentId);
}

/** A group's ancestor chain, nearest parent first, ending at the root. Empty
 *  for a root or an unknown id. Stops on a parent that doesn't resolve and on
 *  a repeat visit, so a cycle yields a finite chain instead of hanging. */
export function groupAncestors(
  groups: ImageGroup[],
  id: string,
): ImageGroup[] {
  const byId = indexById(groups);
  const out: ImageGroup[] = [];
  const seen = new Set<string>([id]);
  const start = byId.get(id);
  let cur = start ? parentOf(start) : null;
  while (cur && !seen.has(cur)) {
    seen.add(cur);
    const g = byId.get(cur);
    if (!g) break; // parent doesn't resolve — the chain ends here
    out.push(g);
    cur = parentOf(g);
  }
  return out;
}

/** Would setting `parentId` as `id`'s parent create a cycle? True for
 *  self-parenting, for a parent that is already a descendant of `id`, and for
 *  a parent whose own ancestor chain is already cyclic — attaching to that
 *  can never yield a valid tree either. False for `null` (clearing a parent
 *  always makes a root) and for a parent that doesn't resolve (dangling, not
 *  cyclic — the caller rejects those separately). */
export function wouldCycle(
  groups: ImageGroup[],
  id: string,
  parentId: string | null,
): boolean {
  if (!parentId) return false;
  if (parentId === id) return true;
  const byId = indexById(groups);
  const seen = new Set<string>([parentId]);
  const start = byId.get(parentId);
  let cur = start ? parentOf(start) : null;
  while (cur) {
    if (cur === id) return true; // id is above the prospective parent
    if (seen.has(cur)) return true; // pre-existing cycle above it
    seen.add(cur);
    const g = byId.get(cur);
    if (!g) return false; // chain ends without reaching id
    cur = parentOf(g);
  }
  return false;
}

/** Normalise a parameter map to what the manifest schema accepts: entries
 *  whose value is a finite number, a string or a boolean survive; anything
 *  else (undefined, null, NaN, Infinity, objects — all unrepresentable in
 *  JSON or unplottable) is dropped, and `unit` is forced to a string or
 *  null. Applied on the way into the store so serialisation is schema-valid
 *  by construction. */
export function normalizeGroupParams(params: GroupParams): GroupParams {
  const out: GroupParams = {};
  for (const [key, p] of Object.entries(params ?? {})) {
    if (!key || !p) continue;
    const v = p.value;
    const ok =
      (typeof v === "number" && Number.isFinite(v)) ||
      typeof v === "string" ||
      typeof v === "boolean";
    if (!ok) continue;
    out[key] = { value: v, unit: typeof p.unit === "string" ? p.unit : null };
  }
  return out;
}

/** Prune a restored group list against the images that actually loaded:
 *  member ids narrow to open images, and a group survives if it has live
 *  members OR a surviving descendant — a project holds its images through
 *  its samples, so an intermediate group with no images of its own is real
 *  structure, not an empty leaf. Every parent that didn't survive, or that
 *  would close a cycle, is cleared to null, so the result is always an
 *  acyclic tree with no dangling references. Fields this function doesn't
 *  understand (params, color, and anything a newer version adds) are carried
 *  through untouched. */
export function pruneGroups(
  groups: ImageGroup[],
  images: Record<string, unknown>,
): ImageGroup[] {
  const pruned = groups.map((g) => ({
    ...g,
    ids: (g.ids ?? []).filter((id) => id in images),
  }));
  const byId = indexById(pruned);
  const keep = new Set<string>();
  for (const g of pruned) {
    if (g.ids.length === 0) continue;
    // keep the group and every ancestor of it; the visited check doubles as
    // the cycle guard
    let cur: ImageGroup | undefined = g;
    while (cur && !keep.has(cur.id)) {
      keep.add(cur.id);
      const p = parentOf(cur);
      cur = p ? byId.get(p) : undefined;
    }
  }
  const kept = pruned.filter((g) => keep.has(g.id));
  return kept.map((g) => {
    const p = parentOf(g);
    if (!p) return g;
    return !keep.has(p) || wouldCycle(kept, g.id, p) ? { ...g, parent: null } : g;
  });
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
