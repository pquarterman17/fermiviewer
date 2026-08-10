// Named compare-group chips in the filmstrip: click to re-select members,
// rename, or delete. Groups bind to compare panes (the panes' dropdowns
// reference them).
//
// Extracted verbatim from Filmstrip.tsx.

import type { ImageGroup } from "../../store/viewer";
import Icon from "../icons/Icon";

export default function GroupsBar({
  groups,
  onRecall,
  onRename,
  onDelete,
}: {
  groups: ImageGroup[];
  onRecall: (ids: string[]) => void;
  onRename: (id: string, name: string) => void;
  onDelete: (id: string) => void;
}) {
  return (
    <div className="fvd-groups-bar">
      <div className="fvd-groups-head">Groups</div>
      {groups.map((g) => (
        <div
          key={g.id}
          className="fvd-group-chip"
          title={`${g.ids.length} images`}
        >
          <button
            className="fvd-group-name"
            onClick={() => onRecall(g.ids)}
            title="Re-select this group's images"
          >
            {g.name} <span className="fvd-group-count">{g.ids.length}</span>
          </button>
          <button
            className="fvd-icon-btn"
            aria-label={`Rename group ${g.name}`}
            title="Rename group"
            onClick={() => {
              const name = window.prompt("Rename group", g.name);
              if (name != null) onRename(g.id, name);
            }}
          >
            <Icon name="edit" />
          </button>
          <button
            className="fvd-icon-btn"
            aria-label={`Delete group ${g.name}`}
            title="Delete group"
            onClick={() => onDelete(g.id)}
          >
            <Icon name="close" />
          </button>
        </div>
      ))}
    </div>
  );
}
