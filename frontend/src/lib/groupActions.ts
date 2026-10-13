// Named-group commands shared by the filmstrip context menu and the
// View → Groups menu: make a group from images, add images to an existing
// group, and show every group side by side.

import { askParams } from "../store/params";
import { useViewer } from "../store/viewer";
import type { ImageGroup } from "./groups";

/** Groups that still have an open image; each becomes one side-by-side pane. */
export function comparableGroupIds(
  groups: ImageGroup[],
  images: Record<string, unknown>,
): string[] {
  return groups.filter((g) => g.ids.some((id) => id in images)).map((g) => g.id);
}

/** One label per group for a picker. Repeated names get a "(2)", "(3)"…
 *  suffix so every option maps back to exactly one group. */
export function groupPickerLabels(groups: ImageGroup[]): string[] {
  const seen = new Map<string, number>();
  return groups.map((g) => {
    const n = (seen.get(g.name) ?? 0) + 1;
    seen.set(g.name, n);
    return n === 1 ? g.name : `${g.name} (${n})`;
  });
}

export async function groupImages(ids: string[]): Promise<void> {
  if (ids.length === 0) return;
  const s = useViewer.getState();
  const values = await askParams("New group", [
    {
      key: "name",
      label: "Name",
      type: "text",
      default: `Group ${s.imageGroups.length + 1}`,
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
  const target = s.imageGroups[labels.indexOf(String(values.group))];
  if (!target || !now.imageGroups.some((g) => g.id === target.id)) return;
  for (const id of ids) now.addGroupMember(target.id, id);
  now.setStatus(`added ${ids.length} to "${target.name}"`);
}

export function compareGroupsSideBySide(): void {
  const s = useViewer.getState();
  s.startSampleCompare(comparableGroupIds(s.imageGroups, s.images));
}
