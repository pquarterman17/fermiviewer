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
import Icon from "../icons/Icon";

interface CtxMenu {
  x: number;
  y: number;
  id: string;
  returnFocus: HTMLDivElement | null;
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
  const cardRefs = useRef<Array<HTMLDivElement | null>>([]);

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
    setCtx({
      x: e.clientX,
      y: e.clientY,
      id,
      returnFocus: e.currentTarget as HTMLDivElement,
    });
  };

  const compareIds = selected.length >= 2 ? selected : null;

  const focusCard = (index: number) => {
    requestAnimationFrame(() => cardRefs.current[index]?.focus());
  };

  const onCardKeyDown = (
    e: React.KeyboardEvent<HTMLDivElement>,
    id: string,
    index: number,
  ) => {
    if (e.key === "ContextMenu" || (e.shiftKey && e.key === "F10")) {
      e.preventDefault();
      if (!selected.includes(id)) select(id, "single");
      const rect = e.currentTarget.getBoundingClientRect();
      setCtx({
        x: rect.left + Math.min(24, rect.width / 2),
        y: rect.top + Math.min(24, rect.height / 2),
        id,
        returnFocus: e.currentTarget,
      });
      return;
    }
    let nextIndex: number | undefined;
    if (e.key === "ArrowDown" || e.key === "ArrowRight") {
      nextIndex = (index + 1) % order.length;
    } else if (e.key === "ArrowUp" || e.key === "ArrowLeft") {
      nextIndex = (index - 1 + order.length) % order.length;
    } else if (e.key === "Home") {
      nextIndex = 0;
    } else if (e.key === "End") {
      nextIndex = order.length - 1;
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      select(
        id,
        e.shiftKey ? "range" : e.metaKey || e.ctrlKey ? "toggle" : "single",
      );
      return;
    } else {
      return;
    }
    e.preventDefault();
    const nextId = nextIndex == null ? undefined : order[nextIndex];
    if (nextId && nextIndex != null) {
      select(nextId, "single");
      focusCard(nextIndex);
    }
  };

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
          <Icon name={listView === "thumbs" ? "list" : "grid"} />
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
          <Icon name="settings" /> Batch {compareIds.length}
        </button>
      )}

      {compareIds && (
        <button
          className="fvd-compare-btn"
          data-tip="Save the selection as a named, reusable compare group"
          onClick={() => createGroup(compareIds)}
        >
          <Icon name="plus" /> Group {compareIds.length}
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

      <div
        className="fvd-film-list"
        role="listbox"
        aria-label="Open images"
        aria-multiselectable="true"
      >
      {order.map((id, index) => {
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
            ref={(node) => {
              cardRefs.current[index] = node;
            }}
            className={cls}
            title={meta.name}
            role="option"
            aria-selected={isSel}
            // activeId can be null while images remain (e.g. undoing a derived
            // image whose parent is gone). Fall back so the listbox always has
            // exactly one tab stop instead of becoming keyboard-unreachable.
            tabIndex={id === (activeId ?? order[0]) ? 0 : -1}
            draggable
            onClick={(e) => select(id, gesture(e))}
            onKeyDown={(e) => onCardKeyDown(e, id, index)}
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
      </div>

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
          dismiss={(restoreFocus = false) => {
            setCtx(null);
            if (restoreFocus) ctx.returnFocus?.focus();
          }}
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
  dismiss: (restoreFocus?: boolean) => void;
}) {
  const refs = useRef<Array<HTMLButtonElement | null>>([]);
  const liveItems = () =>
    refs.current.filter((node): node is HTMLButtonElement => node != null);

  useEffect(() => {
    requestAnimationFrame(() => liveItems()[0]?.focus());
  }, []);

  const focusItem = (index: number) => {
    const items = liveItems();
    if (items.length === 0) return;
    items[(index + items.length) % items.length]?.focus();
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    const items = liveItems();
    const index = items.indexOf(document.activeElement as HTMLButtonElement);
    if (e.key === "ArrowDown") focusItem(index + 1);
    else if (e.key === "ArrowUp") focusItem(index - 1);
    else if (e.key === "Home") focusItem(0);
    else if (e.key === "End") focusItem(items.length - 1);
    else if (e.key === "Escape") dismiss(true);
    else if (e.key === "Tab") {
      // APG: Tab closes the menu and continues the tab sequence. Without this
      // focus walked out to the page while the menu stayed open on screen.
      dismiss(false);
      return;
    } else return;
    e.preventDefault();
    e.stopPropagation();
  };

  const items = [
    { label: "Show in stage", run: onShow },
    { label: "Compare selected", run: onCompare, disabled: !canCompare },
    { label: "Rename…  F2", run: onRename },
    { label: "Close", run: onClose, separator: true },
  ];
  let focusIndex = 0;

  return (
    <div
      className="fvd-menu-dropdown fvd-film-ctx"
      style={{ left: at.x, top: at.y }}
      onMouseDown={(e) => e.stopPropagation()}
      onKeyDown={onKeyDown}
      role="menu"
      aria-label="Image actions"
    >
      {items.map((item) => {
        const index = item.disabled ? -1 : focusIndex++;
        return (
          <div key={item.label} role="presentation">
            {item.separator && <div className="fvd-menu-sep" role="separator" />}
            <button
              ref={(node) => {
                if (index >= 0) refs.current[index] = node;
              }}
              className="fvd-menu-entry"
              role="menuitem"
              // ARIA menus manage focus themselves: every item stays out of
              // the tab sequence and exactly one is focused programmatically.
              tabIndex={-1}
              disabled={item.disabled}
              onClick={() => {
                dismiss(true);
                item.run();
              }}
            >
              <span>{item.label}</span>
            </button>
          </div>
        );
      })}
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
