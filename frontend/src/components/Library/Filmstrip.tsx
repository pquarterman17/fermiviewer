// Left filmstrip / library (handoff §4 "Library", Phase 3): thumbs⇄names
// toggle, ⌘/⇧-click multi-select, HTML5 drag-reorder, right-click context
// menu, Compare N button.
//
// ONE panel that grows (W4 #22): with no sample groups this is exactly the
// flat card list it always was — no section chrome at all. Once groups
// exist the same panel renders them as collapsible sections (projects
// nesting their samples, everything else under "Ungrouped"), and dragging a
// card across a section boundary edits group membership instead of
// reordering. There is no second view and no mode toggle.

import { useEffect, useMemo, useRef, useState } from "react";

import { renameSingleImage } from "../../lib/rename";
import {
  buildSampleTree,
  entryKey,
  UNGROUPED_SECTION,
  visibleEntries,
  type FilmEntry,
} from "../../lib/sampleTree";
import { useViewer, type SelectGesture } from "../../store/viewer";
import Icon from "../icons/Icon";
import { useCollapsedGroups } from "../Inspector/useCollapsedGroups";
import FilmCard, { type FilmCardCtx } from "./FilmCard";
import FilmstripContextMenu, {
  type FilmstripCtxTarget,
} from "./FilmstripContextMenu";
import GroupsBar from "./GroupsBar";
import SampleSection, { type SampleSectionCtx } from "./SampleSection";
import UnavailableSection from "./UnavailableSection";

type CtxMenu = FilmstripCtxTarget;

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
  const unavailable = useViewer((s) => s.unavailable);
  const createGroup = useViewer((s) => s.createGroup);
  const renameGroup = useViewer((s) => s.renameGroup);
  const deleteGroup = useViewer((s) => s.deleteGroup);
  const addGroupMember = useViewer((s) => s.addGroupMember);
  const removeGroupMember = useViewer((s) => s.removeGroupMember);

  const [ctx, setCtx] = useState<CtxMenu | null>(null);
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  const [dropSection, setDropSection] = useState<string | null>(null);
  const dragId = useRef<string | null>(null);
  // section the drag started in (null = Ungrouped / the flat list), so a drop
  // can tell "reorder within this section" from "move between sections"
  const dragFrom = useRef<string | null>(null);
  const cardRefs = useRef<Array<HTMLDivElement | null>>([]);

  const { collapsed, toggle } = useCollapsedGroups("library");
  const hasGroups = imageGroups.length > 0;
  // a project whose data has moved can have placeholders and no open images —
  // "No images open. File → Open…" would be wrong advice there (#35)
  const hasUnavailable = Object.keys(unavailable).length > 0;
  // derived in a memo, never in a selector: these build fresh arrays, and a
  // selector that returns one re-renders forever (zustand snapshot rule)
  const tree = useMemo(
    () => buildSampleTree(imageGroups, images, order),
    [imageGroups, images, order],
  );
  // With no groups the panel is the flat list it always was — no sections, so
  // no collapse state can hide a card either.
  const entries: FilmEntry[] = useMemo(
    () =>
      hasGroups
        ? visibleEntries(tree, collapsed)
        : order.map((id) => ({ id, groupId: null })),
    [hasGroups, tree, collapsed, order],
  );
  const posOf = useMemo(() => {
    const at = new Map(entries.map((e, i) => [entryKey(e), i]));
    return (key: string) => at.get(key) ?? -1;
  }, [entries]);
  // exactly one tab stop: the active image's card, else the first one
  const activePos = entries.findIndex((e) => e.id === activeId);
  const tabPos = activePos === -1 ? 0 : activePos;

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

  // arrow keys walk the VISIBLE card sequence, which with no groups is
  // `order` itself and with groups runs on across section boundaries
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
    const n = entries.length;
    let nextIndex: number | undefined;
    if (e.key === "ArrowDown" || e.key === "ArrowRight") {
      nextIndex = (index + 1) % n;
    } else if (e.key === "ArrowUp" || e.key === "ArrowLeft") {
      nextIndex = (index - 1 + n) % n;
    } else if (e.key === "Home") {
      nextIndex = 0;
    } else if (e.key === "End") {
      nextIndex = n - 1;
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
    const nextId = nextIndex == null ? undefined : entries[nextIndex]?.id;
    if (nextId && nextIndex != null) {
      select(nextId, "single");
      focusCard(nextIndex);
    }
  };

  /** Cross-section drop: membership edit, not a reorder. */
  const moveBetween = (id: string, from: string | null, into: string | null) => {
    if (from === into) return;
    if (from) removeGroupMember(from, id);
    if (into) addGroupMember(into, id);
  };

  const endDrag = () => {
    dragId.current = null;
    dragFrom.current = null;
    setDropTarget(null);
    setDropSection(null);
  };

  const cardCtx: FilmCardCtx = {
    images,
    listView,
    activeId,
    selected,
    dropTarget,
    tabPos,
    posOf,
    registerRef: (pos, node) => {
      cardRefs.current[pos] = node;
    },
    select: (e, id) => select(id, gesture(e)),
    keyDown: onCardKeyDown,
    contextMenu: onContextMenu,
    dragStart: (id, from) => {
      dragId.current = id;
      dragFrom.current = from;
    },
    dragOver: (key, id, into) => {
      // only hint "drop before this card" when the drop would reorder; a
      // cross-section drop is a membership change and highlights the section
      if (dragId.current && dragId.current !== id && into === dragFrom.current) {
        setDropTarget(key);
      }
    },
    dragLeave: (key) => setDropTarget((t) => (t === key ? null : t)),
    drop: (id, into) => {
      const src = dragId.current;
      if (src) {
        if (into === dragFrom.current) reorder(src, id);
        else moveBetween(src, dragFrom.current, into);
      }
      endDrag();
    },
    dragEnd: endDrag,
  };

  const sectionCtx: SampleSectionCtx = {
    collapsed,
    toggle,
    dropSection,
    sectionDragOver: (sectionId, into) => {
      if (dragId.current && into !== dragFrom.current) setDropSection(sectionId);
    },
    sectionDragLeave: (sectionId) =>
      setDropSection((s) => (s === sectionId ? null : s)),
    // a card's own onDrop runs first and clears dragId, so this only fires for
    // a drop on the section's chrome/gaps — never twice for one drop
    sectionDrop: (into) => {
      const src = dragId.current;
      if (src) moveBetween(src, dragFrom.current, into);
      endDrag();
    },
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
          data-tip-detail="Switch between image previews and a compact filename list."
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
          data-tip-detail="Open the selection in linked panes for synchronized review."
          onClick={() => startCompare(compareIds)}
        >
          Compare {compareIds.length}
        </button>
      )}

      {compareIds && (
        <button
          className="fvd-compare-btn"
          data-tip="Build a recipe and apply it to the selected images"
          data-tip-detail="Chain reusable operations across every selected image."
          onClick={() => setBatchOpen(true)}
        >
          <Icon name="settings" /> Batch {compareIds.length}
        </button>
      )}

      {compareIds && (
        <button
          className="fvd-compare-btn"
          data-tip="Save the selection as a named, reusable compare group"
          data-tip-detail="Recall this exact set later without reselecting each image."
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

      {order.length === 0 && !hasUnavailable && (
        <div className="fvd-film-empty">
          No images open.
          <br />
          File → Open…
        </div>
      )}

      {/* Placeholders for a project whose data has moved (#35). Above the
          cards on purpose: it is the one thing in the library the user has to
          act on, and it renders nothing at all when nothing is missing. */}
      <UnavailableSection />

      <div
        className="fvd-film-list"
        role="listbox"
        aria-label="Open images"
        aria-multiselectable="true"
      >
      {!hasGroups &&
        entries.map((e) => (
          <FilmCard key={entryKey(e)} id={e.id} groupId={null} ctx={cardCtx} />
        ))}

      {hasGroups &&
        tree.roots.map((node) => (
          <SampleSection
            key={node.group.id}
            sectionId={node.group.id}
            name={node.group.name}
            groupId={node.group.id}
            depth={node.depth}
            ids={node.ids}
            subsections={node.children}
            ctx={cardCtx}
            sec={sectionCtx}
          />
        ))}

      {hasGroups && tree.ungrouped.length > 0 && (
        <SampleSection
          sectionId={UNGROUPED_SECTION}
          name="Ungrouped"
          groupId={null}
          depth={0}
          ids={tree.ungrouped}
          subsections={[]}
          ctx={cardCtx}
          sec={sectionCtx}
        />
      )}
      </div>

      {ctx && (
        <FilmstripContextMenu
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
