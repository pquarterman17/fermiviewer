// Left filmstrip / library (handoff §4 "Library", Phase 3): thumbs⇄names
// toggle, ⌘/⇧-click multi-select, HTML5 drag-reorder, right-click context
// menu, Compare N button.

import { useEffect, useRef, useState } from "react";

import { renderUrl } from "../../lib/api";
import { renameSingleImage } from "../../lib/rename";
import {
  useViewer,
  type ImageGroup,
  type SelectGesture,
} from "../../store/viewer";

interface CtxMenu {
  x: number;
  y: number;
  id: string;
}

export default function Filmstrip() {
  const order = useViewer((s) => s.order);
  const images = useViewer((s) => s.images);
  const activeId = useViewer((s) => s.activeId);
  const selected = useViewer((s) => s.selected);
  const listView = useViewer((s) => s.listView);
  const setListView = useViewer((s) => s.setListView);
  const select = useViewer((s) => s.select);
  const reorder = useViewer((s) => s.reorder);
  const startCompare = useViewer((s) => s.startCompare);
  const closeImage = useViewer((s) => s.closeImage);
  const setBatchOpen = useViewer((s) => s.setBatchOpen);
  const imageGroups = useViewer((s) => s.imageGroups);
  const createGroup = useViewer((s) => s.createGroup);
  const renameGroup = useViewer((s) => s.renameGroup);
  const deleteGroup = useViewer((s) => s.deleteGroup);

  const [ctx, setCtx] = useState<CtxMenu | null>(null);
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  const dragId = useRef<string | null>(null);

  useEffect(() => {
    if (!ctx) return;
    const close = () => setCtx(null);
    window.addEventListener("mousedown", close);
    window.addEventListener("blur", close);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("blur", close);
    };
  }, [ctx]);

  const gesture = (e: React.MouseEvent): SelectGesture =>
    e.shiftKey ? "range" : e.metaKey || e.ctrlKey ? "toggle" : "single";

  const onContextMenu = (e: React.MouseEvent, id: string) => {
    e.preventDefault();
    // right-click outside the selection moves selection (native idiom)
    if (!selected.includes(id)) select(id, "single");
    setCtx({ x: e.clientX, y: e.clientY, id });
  };

  const compareIds = selected.length >= 2 ? selected : null;

  return (
    <aside className="fvd-filmstrip">
      <div className="fvd-film-head">
        <span className="count">{order.length}</span>
        <button
          className="fvd-icon-btn"
          aria-label={listView === "thumbs" ? "Show image names" : "Show thumbnails"}
          aria-pressed={listView === "names"}
          data-tip={listView === "thumbs" ? "Names view" : "Thumbnail view"}
          onClick={() =>
            setListView(listView === "thumbs" ? "names" : "thumbs")
          }
        >
          {listView === "thumbs" ? "☰" : "▦"}
        </button>
      </div>

      {compareIds && (
        <button
          className="fvd-compare-btn"
          data-tip="Compare the selected images"
          onClick={() => startCompare(compareIds)}
        >
          Compare {compareIds.length}
        </button>
      )}

      {compareIds && (
        <button
          className="fvd-compare-btn"
          data-tip="Build a recipe and apply it to the selected images"
          onClick={() => setBatchOpen(true)}
        >
          ⚙ Batch {compareIds.length}
        </button>
      )}

      {compareIds && (
        <button
          className="fvd-compare-btn"
          data-tip="Save the selection as a named, reusable compare group"
          onClick={() => createGroup(compareIds)}
        >
          ＋ Group {compareIds.length}
        </button>
      )}

      {imageGroups.length > 0 && (
        <GroupsBar
          groups={imageGroups}
          onRecall={(ids) => {
            // re-select the group's members so it's easy to act on / re-group
            const live = ids.filter((id) => id in images);
            live.forEach((id, i) => select(id, i === 0 ? "single" : "toggle"));
          }}
          onRename={renameGroup}
          onDelete={deleteGroup}
        />
      )}

      {order.length === 0 && (
        <div className="fvd-film-empty">
          No images open.
          <br />
          File → Open…
        </div>
      )}

      {order.map((id) => {
        const meta = images[id];
        if (!meta) return null;
        const isSel = selected.includes(id);
        const cls = [
          "fvd-film-card",
          listView === "names" ? "names" : "",
          id === activeId ? "active" : "",
          isSel ? "selected" : "",
          dropTarget === id ? "drop-before" : "",
        ]
          .filter(Boolean)
          .join(" ");
        return (
          <div
            key={id}
            className={cls}
            title={meta.name}
            draggable
            onClick={(e) => select(id, gesture(e))}
            onContextMenu={(e) => onContextMenu(e, id)}
            onDragStart={(e) => {
              dragId.current = id;
              e.dataTransfer.effectAllowed = "move";
            }}
            onDragOver={(e) => {
              e.preventDefault();
              if (dragId.current && dragId.current !== id) setDropTarget(id);
            }}
            onDragLeave={() => setDropTarget((t) => (t === id ? null : t))}
            onDrop={(e) => {
              e.preventDefault();
              if (dragId.current) reorder(dragId.current, id);
              dragId.current = null;
              setDropTarget(null);
            }}
            onDragEnd={() => {
              dragId.current = null;
              setDropTarget(null);
            }}
          >
            {listView === "thumbs" &&
              (meta.kind === "spectrum" ? (
                // 1-D spectra have no raster (backend 400s on /render)
                <div className="fvd-film-thumb fvd-film-spectrum">⌇</div>
              ) : (
                <img
                  className="fvd-film-thumb"
                  src={renderUrl(id)}
                  alt={meta.name}
                  draggable={false}
                />
              ))}
            <div className="fvd-film-name">{meta.name}</div>
          </div>
        );
      })}

      {ctx && (
        <ContextMenu
          at={ctx}
          canCompare={selected.length >= 2}
          onShow={() => select(ctx.id, "single")}
          onCompare={() => startCompare(selected)}
          onRename={() => void renameSingleImage(ctx.id)}
          onClose={() => {
            for (const id of selected.includes(ctx.id) ? selected : [ctx.id]) {
              void closeImage(id);
            }
          }}
          dismiss={() => setCtx(null)}
        />
      )}
    </aside>
  );
}

function ContextMenu({
  at,
  canCompare,
  onShow,
  onCompare,
  onRename,
  onClose,
  dismiss,
}: {
  at: CtxMenu;
  canCompare: boolean;
  onShow: () => void;
  onCompare: () => void;
  onRename: () => void;
  onClose: () => void;
  dismiss: () => void;
}) {
  const item = (label: string, run: () => void, disabled = false) => (
    <div
      className={`fvd-menu-entry${disabled ? " disabled" : ""}`}
      onMouseDown={(e) => {
        e.stopPropagation();
        dismiss();
        run();
      }}
    >
      <span>{label}</span>
    </div>
  );

  return (
    <div
      className="fvd-menu-dropdown fvd-film-ctx"
      style={{ left: at.x, top: at.y }}
      onMouseDown={(e) => e.stopPropagation()}
    >
      {item("Show in stage", onShow)}
      {item("Compare selected", onCompare, !canCompare)}
      {item("Rename…  F2", onRename)}
      <div className="fvd-menu-sep" />
      {item("Close", onClose)}
    </div>
  );
}

/** Named compare-group chips: click to re-select members, rename, or delete.
 *  Groups bind to compare panes (the panes' dropdowns reference them). */
function GroupsBar({
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
            ✎
          </button>
          <button
            className="fvd-icon-btn"
            aria-label={`Delete group ${g.name}`}
            title="Delete group"
            onClick={() => onDelete(g.id)}
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
