// Named-group commands shared by the filmstrip context menu and the
// View → Groups menu: make a group from images, add images to an existing
// group, and show every group side by side.

import { askParams } from "../store/params";
import { useViewer } from "../store/viewer";
import { groupAncestors, type ImageGroup } from "./groups";

/** Groups that still have an open image; each becomes one side-by-side pane. */
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
  ]);
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

export function compareGroupsSideBySide(): void {
  const s = useViewer.getState();
  s.startSampleCompare(comparableGroupIds(s.imageGroups, s.images));
}
