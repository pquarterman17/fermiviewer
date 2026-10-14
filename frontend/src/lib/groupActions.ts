// Named-group commands shared by the filmstrip context menu and the
// View → Groups menu: make a group, add to or remove from groups, delete
// groups, and show two groups side by side.

import { askParams } from "../store/params";
import { useViewer } from "../store/viewer";
import { groupAncestors, type ImageGroup } from "./groups";

/** Groups that still have an open image, i.e. ones a side-by-side pane can
 *  show. */
export function comparableGroupIds(
  groups: ImageGroup[],
  images: Record<string, unknown>,
): string[] {
  return groups.filter((g) => g.ids.some((id) => id in images)).map((g) => g.id);
}

/** One label per group for a picker: its path from the root project
 *  ("Project / Sample"), so samples with the same name in different projects
 *  stay distinguishable. Labels that still repeat get a "(2)", "(3)"…
 *  suffix so every option maps back to exactly one group. */
export function groupPickerLabels(groups: ImageGroup[]): string[] {
  const seen = new Map<string, number>();
  return groups.map((g) => {
    const path = [...groupAncestors(groups, g.id)]
      .reverse()
      .map((a) => a.name)
      .concat(g.name)
      .join(" / ");
    const n = (seen.get(path) ?? 0) + 1;
    seen.set(path, n);
    return n === 1 ? path : `${path} (${n})`;
  });
}

/** "Group N" with the smallest N no existing group is already called. */
export function nextGroupName(groups: ImageGroup[]): string {
  const taken = new Set(groups.map((g) => g.name));
  // N groups can take at most N names, so one of 1..N+1 is always free
  let n = 1;
  while (taken.has(`Group ${n}`)) n++;
  return `Group ${n}`;
}

export async function groupImages(ids: string[]): Promise<void> {
  if (ids.length === 0) return;
  const s = useViewer.getState();
  const values = await askParams("New group", [
    {
      key: "name",
      label: "Name",
      type: "text",
      default: nextGroupName(s.imageGroups),
    },
  ], "OK");
  if (values) useViewer.getState().createGroup(ids, String(values.name));
}

export async function addImagesToGroup(ids: string[]): Promise<void> {
  const s = useViewer.getState();
  if (ids.length === 0 || s.imageGroups.length === 0) return;
  const labels = groupPickerLabels(s.imageGroups);
  const values = await askParams(
    `Add ${ids.length} image${ids.length === 1 ? "" : "s"} to group`,
    [
      {
        key: "group",
        label: "Group",
        type: "select",
        default: labels[0],
        options: labels,
      },
    ],
    "Add",
  );
  if (!values) return;
  const now = useViewer.getState();
  // the group list can change while the dialog is open; resolve by label
  // against the list the dialog was built from, then confirm it still exists
  const picked = s.imageGroups[labels.indexOf(String(values.group))];
  const target = picked && now.imageGroups.find((g) => g.id === picked.id);
  if (!target) return;
  const before = new Set(target.ids);
  const added = ids.filter((id) => id in now.images && !before.has(id));
  for (const id of added) now.addGroupMember(target.id, id);
  now.setStatus(
    added.length === 0
      ? `already in "${target.name}"`
      : `added ${added.length} to "${target.name}"`,
  );
}

/** The two groups a group side-by-side shows: groups holding the selected
 *  images come first, then the remaining comparable groups in list order.
 *  Fewer than two means there is nothing to compare. */
export function sideBySidePair(
  groups: ImageGroup[],
  images: Record<string, unknown>,
  selected: string[],
): string[] {
  const comparable = comparableGroupIds(groups, images);
  const chosen = new Set(selected);
  const touched = comparable.filter((id) =>
    groups.find((g) => g.id === id)?.ids.some((m) => chosen.has(m)),
  );
  const ordered = [...touched, ...comparable.filter((id) => !touched.includes(id))];
  return ordered.slice(0, 2);
}

export function compareGroupsSideBySide(): void {
  const s = useViewer.getState();
  const pair = sideBySidePair(s.imageGroups, s.images, s.selected);
  if (pair.length < 2) {
    s.setStatus("need two groups with open images to compare");
    return;
  }
  s.startSampleCompare(pair);
}

/** Groups any of `ids` belongs to. */
export function groupsContaining(groups: ImageGroup[], ids: string[]): ImageGroup[] {
  const wanted = new Set(ids);
  return groups.filter((g) => g.ids.some((m) => wanted.has(m)));
}

/** Take the images out of every group they are in. The groups themselves
 *  stay, even when emptied — delete a group to remove it. */
export function removeImagesFromGroups(ids: string[]): void {
  const s = useViewer.getState();
  const touched = groupsContaining(s.imageGroups, ids);
  if (touched.length === 0) {
    s.setStatus("not in any group");
    return;
  }
  for (const g of touched) {
    for (const id of ids) if (g.ids.includes(id)) s.removeGroupMember(g.id, id);
  }
  s.setStatus(
    `removed from ${touched.length} group${touched.length === 1 ? "" : "s"}`,
  );
}

/** Pick a group and delete it. Its images stay open. */
export async function deleteGroupPicked(): Promise<void> {
  const s = useViewer.getState();
  if (s.imageGroups.length === 0) return;
  const labels = groupPickerLabels(s.imageGroups);
  const values = await askParams("Delete group (images stay open)", [
    { key: "group", label: "Group", type: "select", default: labels[0], options: labels },
  ], "Delete");
  if (!values) return;
  const picked = s.imageGroups[labels.indexOf(String(values.group))];
  const now = useViewer.getState();
  if (!picked || !now.imageGroups.some((g) => g.id === picked.id)) return;
  now.deleteGroup(picked.id);
  now.setStatus(`deleted group "${picked.name}"`);
}

/** Delete every group after confirming. Images stay open. */
export function deleteAllGroups(): void {
  const s = useViewer.getState();
  const n = s.imageGroups.length;
  if (n === 0) return;
  if (!window.confirm(`Delete all ${n} group${n === 1 ? "" : "s"}? Images stay open.`)) {
    return;
  }
  for (const g of s.imageGroups) s.deleteGroup(g.id);
  s.setStatus(`deleted ${n} group${n === 1 ? "" : "s"}`);
}
