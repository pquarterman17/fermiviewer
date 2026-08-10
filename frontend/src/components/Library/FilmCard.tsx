// One filmstrip card: thumb-or-name, selection, HTML5 drag, context menu.
// Extracted verbatim from Filmstrip.tsx (W4 #22) so the flat list and the
// nested sample sections render exactly the same card — the no-groups
// filmstrip must stay byte-identical to what it was before sections existed.

import { renderUrl, type ImageMeta } from "../../lib/api";
import { entryKey } from "../../lib/sampleTree";
import type { ListView } from "../../store/viewerTypes";

/** Everything a card needs from Filmstrip, bundled into one object so the
 *  section tree can hand it down unchanged instead of re-drilling a dozen
 *  props per level.
 *
 *  Section-aware handlers take the card's `groupId` (null = Ungrouped / flat
 *  list) so Filmstrip can tell a reorder inside one section from a
 *  membership change across two. `dropTarget` and `posOf` are keyed by
 *  entryKey, not by image id, because one image may be rendered in several
 *  sections. */
export interface FilmCardCtx {
  images: Record<string, ImageMeta>;
  listView: ListView;
  activeId: string | null;
  selected: string[];
  dropTarget: string | null;
  /** Position in the visible card sequence that owns the listbox tab stop. */
  tabPos: number;
  posOf: (key: string) => number;
  registerRef: (pos: number, node: HTMLDivElement | null) => void;
  select: (e: React.MouseEvent, id: string) => void;
  keyDown: (e: React.KeyboardEvent<HTMLDivElement>, id: string, pos: number) => void;
  contextMenu: (e: React.MouseEvent, id: string) => void;
  dragStart: (id: string, from: string | null) => void;
  dragOver: (key: string, id: string, into: string | null) => void;
  dragLeave: (key: string) => void;
  drop: (id: string, into: string | null) => void;
  dragEnd: () => void;
}

export default function FilmCard({
  id,
  groupId,
  ctx,
}: {
  id: string;
  groupId: string | null;
  ctx: FilmCardCtx;
}) {
  const meta = ctx.images[id];
  if (!meta) return null;
  const key = entryKey({ id, groupId });
  const pos = ctx.posOf(key);
  const isSel = ctx.selected.includes(id);
  const cls = [
    "fvd-film-card",
    ctx.listView === "names" ? "names" : "",
    id === ctx.activeId ? "active" : "",
    isSel ? "selected" : "",
    ctx.dropTarget === key ? "drop-before" : "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <div
      ref={(node) => {
        ctx.registerRef(pos, node);
      }}
      className={cls}
      title={meta.name}
      role="option"
      aria-selected={isSel}
      // activeId can be null while images remain (e.g. undoing a derived
      // image whose parent is gone). Fall back so the listbox always has
      // exactly one tab stop instead of becoming keyboard-unreachable.
      tabIndex={pos === ctx.tabPos ? 0 : -1}
      draggable
      onClick={(e) => ctx.select(e, id)}
      onKeyDown={(e) => ctx.keyDown(e, id, pos)}
      onContextMenu={(e) => ctx.contextMenu(e, id)}
      onDragStart={(e) => {
        ctx.dragStart(id, groupId);
        e.dataTransfer.effectAllowed = "move";
      }}
      onDragOver={(e) => {
        e.preventDefault();
        ctx.dragOver(key, id, groupId);
      }}
      onDragLeave={() => ctx.dragLeave(key)}
      onDrop={(e) => {
        e.preventDefault();
        ctx.drop(id, groupId);
      }}
      onDragEnd={() => ctx.dragEnd()}
    >
      {ctx.listView === "thumbs" &&
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
}
