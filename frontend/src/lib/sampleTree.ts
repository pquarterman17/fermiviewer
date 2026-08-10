// Pure derivation of the filmstrip's sample tree (W4 #22): the sample /
// project groups of lib/groups.ts plus the open images, turned into the
// sections the filmstrip renders and the flat card sequence its arrow keys
// walk.
//
// These build fresh arrays on every call, so they must never be called
// inside a zustand selector (a selector has to return a stable snapshot or
// the subscriber re-renders forever). Filmstrip calls them from a useMemo.

import { groupChildren, type ImageGroup } from "./groups";

/** One group rendered as one filmstrip section. `ids` are its live members
 *  in library (`order`) order, so a drag-reorder of the flat list still
 *  reorders within a section; `children` are the sections nested inside it,
 *  which is how a project holds its samples. */
export interface SampleNode {
  group: ImageGroup;
  /** 0 for a root; +1 per level of nesting. Drives the indent only. */
  depth: number;
  ids: string[];
  children: SampleNode[];
}

/** The sections the filmstrip renders: the root groups, plus every open
 *  image no rendered section claims. */
export interface SampleTree {
  roots: SampleNode[];
  ungrouped: string[];
}

/** One rendered card: the image, and the group whose section it sits in —
 *  null for the Ungrouped section, and for every card in the flat, no-groups
 *  filmstrip. */
export interface FilmEntry {
  id: string;
  groupId: string | null;
}

/** Collapse key of the synthetic "Ungrouped" section. Not a group id: the
 *  cards inside it carry `groupId: null`, because dropping onto them means
 *  "belongs to no sample". */
export const UNGROUPED_SECTION = "__ungrouped__";

/** Stable identity for a rendered card. An image may sit in more than one
 *  group and so be rendered more than once; the id alone does not identify a
 *  card, the (section, image) pair does. */
export function entryKey(e: FilmEntry): string {
  return `${e.groupId ?? ""}:${e.id}`;
}

/** Build the section tree from the store's groups and open images.
 *
 *  Walks down from the roots (`groupChildren(groups, null)`), so it is
 *  bounded by construction: a group caught in a parent cycle is never
 *  reachable from a root, and a repeat visit is skipped besides. Nothing can
 *  hide an image — `ungrouped` is whatever the walk did not claim, so a group
 *  the walk cannot reach donates its images back to the Ungrouped section
 *  instead of dropping them off the filmstrip. */
export function buildSampleTree(
  groups: ImageGroup[],
  images: Record<string, unknown>,
  order: string[],
): SampleTree {
  const claimed = new Set<string>();
  const visited = new Set<string>();

  const build = (parentId: string | null, depth: number): SampleNode[] =>
    groupChildren(groups, parentId).flatMap((group) => {
      if (visited.has(group.id)) return [];
      visited.add(group.id);
      const members = new Set(group.ids.filter((id) => id in images));
      const ids = order.filter((id) => members.has(id));
      for (const id of ids) claimed.add(id);
      return [{ group, depth, ids, children: build(group.id, depth + 1) }];
    });

  const roots = build(null, 0);
  return { roots, ungrouped: order.filter((id) => !claimed.has(id)) };
}

/** Flatten the tree into the visual card sequence, in DOM order (a section's
 *  own cards, then its subsections, then the Ungrouped section last), and
 *  skipping collapsed subtrees entirely. Arrow keys step through this list,
 *  so they only ever land on a card that is actually on screen — including
 *  across section boundaries. */
export function visibleEntries(
  tree: SampleTree,
  collapsed: ReadonlySet<string>,
): FilmEntry[] {
  const out: FilmEntry[] = [];
  const walk = (nodes: SampleNode[]): void => {
    for (const n of nodes) {
      if (collapsed.has(n.group.id)) continue;
      for (const id of n.ids) out.push({ id, groupId: n.group.id });
      walk(n.children);
    }
  };
  walk(tree.roots);
  if (!collapsed.has(UNGROUPED_SECTION)) {
    for (const id of tree.ungrouped) out.push({ id, groupId: null });
  }
  return out;
}
