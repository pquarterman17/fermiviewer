// Left filmstrip / library (handoff §4 "Library", Phase 3): thumbs⇄names
// toggle, ⌘/⇧-click multi-select, HTML5 drag-reorder, right-click context
// menu, Compare N button.

import { useEffect, useRef, useState } from "react";

import { renderUrl } from "../../lib/api";
import { renameSingleImage } from "../../lib/rename";
import { useViewer, type SelectGesture } from "../../store/viewer";

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
        <span className="count">DOCS · {order.length}</span>
        <button
          className="fvd-icon-btn"
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
          onClick={() => startCompare(compareIds)}
        >
          Compare {compareIds.length}
        </button>
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
