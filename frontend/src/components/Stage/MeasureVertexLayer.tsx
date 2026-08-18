// Per-vertex handle rendering + drag mechanics for the measure overlay —
// split out of MeasureOverlay.tsx (lasso-editing plan, item D) to keep that
// drag-heavy SVG component under the frontend size ratchet. Owns the ONE
// drag ref shared by every handle drag, whole-body translate (pt === -1)
// and — new in this item — alt+edge-drag vertex insertion, since all three
// gestures are just different ways of arming the same pointermove/pointerup
// pair (dragRef.current.pt tells onHandleMove which one is in flight).

import { useRef } from "react";

import { screenToImage, type Size } from "../../lib/geometry";
import type { EndSymbol, Measure, UndoEntry, View } from "../../store/viewer";
import { EndpointGlyph } from "./measureGlyphs";

/** One in-flight drag: a vertex (`pt` = its index) or the whole body
 *  (`pt === -1`, audit #12). `before` is the pts snapshot at drag START —
 *  compared against the live pts on release to decide whether an undo
 *  entry is needed, and to seed it. `beforeHoles`/`holes0` are the same
 *  idea for holes (holes-detach fix) — set only by a body drag, since a
 *  per-vertex drag never moves holes. */
export interface VertexDragState {
  mid: string;
  pt: number;
  before: Measure["pts"];
  beforeHoles?: Measure["holes"];
  startX?: number; // client px at drag start (body drag only)
  startY?: number;
  pts0?: Measure["pts"]; // snapshot of all pts at drag start (body drag only)
  holes0?: Measure["holes"]; // snapshot of holes at drag start (body drag only)
}

export interface VertexEditCtx {
  imageId: string;
  measures: Measure[];
  view: View;
  img: Size;
  vp: Size;
  svgRef: React.RefObject<SVGSVGElement | null>;
  updateMeasure: (
    imageId: string,
    measureId: string,
    pts: Measure["pts"],
    holes?: Measure["holes"],
  ) => void;
  setSelected: (id: string) => void;
  pushUndo: (e: UndoEntry) => void;
  /** post-edit analysis refresh (Convention 1) — a no-op for kinds whose
   *  label is a pure function of pts (polygon/lasso area), since those
   *  recompute for free on the next render once the store pts change. */
  refresh: (m: Measure) => void;
  /** Opens the measure context menu at the pointer, extended with the
   *  right-clicked vertex index — MeasureOverlay owns the `ctxMenu` state
   *  itself (same idiom as its own shape/label context-menu openers). */
  openMenu: (e: React.MouseEvent, mid: string, vertexIndex: number) => void;
}

export interface VertexEditApi {
  onHandleDown: (e: React.PointerEvent, mid: string, pt: number) => void;
  onHandleMove: (e: React.PointerEvent) => void;
  onHandleUp: (e: React.PointerEvent) => void;
  /** Mousedown on a measure's BODY (fill/perimeter hit target) — one
   *  entrypoint shared by every kind. Plain drag translates the whole
   *  measure (Convention 6, unchanged). Alt+drag on a polygon/lasso EDGE
   *  instead inserts a vertex at the grab point (projected onto that
   *  segment) and arms the SAME per-vertex drag machinery as
   *  onHandleDown to move it — one fluid gesture, one undo entry (the
   *  pre-insert ring is `before`). Every other kind, and non-alt drags on
   *  polygon/lasso, fall through to the plain translate unchanged. */
  onBodyDown: (
    e: React.PointerEvent,
    m: Measure,
    screenPts: { x: number; y: number }[],
  ) => void;
  onVertexContextMenu: (
    e: React.MouseEvent,
    mid: string,
    vertexIndex: number,
  ) => void;
}

/** Alt+edge-drag insert only fires when the pointer actually came down
 *  NEAR an edge (screen px — `bestDist` below is computed against
 *  `screenPts`, the layer's own screen-space render coordinates). Beyond
 *  this, a down-point deep in a shape's interior falls through to the
 *  plain body translate instead of inserting a vertex at the (possibly
 *  very distant) nearest-edge projection and teleporting it to the
 *  pointer on the first move — the interior-alt-drag spike bug this
 *  gate exists to kill. */
const EDGE_INSERT_MAX_DIST_PX = 12;

/** Closest point to `p` on segment a→b, plus the distance to it. */
function projectToSegment(
  p: { x: number; y: number },
  a: { x: number; y: number },
  b: { x: number; y: number },
): { proj: { x: number; y: number }; dist: number } {
  const abx = b.x - a.x;
  const aby = b.y - a.y;
  const len2 = abx * abx + aby * aby;
  const t =
    len2 === 0
      ? 0
      : Math.min(1, Math.max(0, ((p.x - a.x) * abx + (p.y - a.y) * aby) / len2));
  const proj = { x: a.x + abx * t, y: a.y + aby * t };
  return { proj, dist: Math.hypot(p.x - proj.x, p.y - proj.y) };
}

export function useVertexEditing(ctx: VertexEditCtx): VertexEditApi {
  const {
    imageId,
    measures,
    view,
    img,
    vp,
    svgRef,
    updateMeasure,
    setSelected,
    pushUndo,
    refresh,
    openMenu,
  } = ctx;
  const dragRef = useRef<VertexDragState | null>(null);

  const onHandleDown = (e: React.PointerEvent, mid: string, pt: number) => {
    e.stopPropagation();
    const m = measures.find((x) => x.id === mid);
    // beforeHoles is snapshotted even though a per-vertex drag never moves
    // holes — onHandleUp's holesChanged check needs a real "before" value
    // to compare against, not undefined, or it would misread an untouched
    // holes field as changed and wipe it on undo.
    dragRef.current = { mid, pt, before: m ? m.pts : [], beforeHoles: m?.holes };
    (e.target as Element).setPointerCapture(e.pointerId);
    setSelected(mid);
  };

  const onHandleMove = (e: React.PointerEvent) => {
    if (!dragRef.current || !svgRef.current) return;
    const { mid, pt } = dragRef.current;
    const m = measures.find((x) => x.id === mid);
    if (!m) return;

    if (pt === -1) {
      // whole-body translate (audit #12) — holes (if any) move by the SAME
      // delta as pts, in the same updateMeasure call, so a region's holes
      // stay attached to it instead of being left behind (holes-detach fix).
      const { startX, startY, pts0, holes0 } = dragRef.current;
      if (startX == null || startY == null || !pts0) return;
      const dx = (e.clientX - startX) / (view.z * img.w);
      const dy = (e.clientY - startY) / (view.z * img.h);
      const shift = (p: { x: number; y: number }) => ({
        x: Math.min(1, Math.max(0, p.x + dx)),
        y: Math.min(1, Math.max(0, p.y + dy)),
      });
      const pts = pts0.map(shift);
      const holes = holes0?.map((ring) => ring.map(shift));
      updateMeasure(imageId, mid, pts, holes);
      return;
    }

    const r = svgRef.current.getBoundingClientRect();
    const ip = screenToImage(
      e.clientX - r.left,
      e.clientY - r.top,
      view,
      img,
      vp,
    );
    const nx = Math.min(1, Math.max(0, ip.x / img.w));
    const ny = Math.min(1, Math.max(0, ip.y / img.h));
    const pts = m.pts.map((p, i) => (i === pt ? { x: nx, y: ny } : p));
    updateMeasure(imageId, mid, pts);
  };

  const onHandleUp = (e: React.PointerEvent) => {
    if (!dragRef.current) return;
    const { mid, before, beforeHoles } = dragRef.current;
    const m = measures.find((x) => x.id === mid);
    dragRef.current = null;
    (e.target as Element).releasePointerCapture(e.pointerId);
    if (!m) return;
    const ptsChanged =
      before.length && JSON.stringify(before) !== JSON.stringify(m.pts);
    // holes-detach fix: beforeHoles is set only by a body drag (never by a
    // per-vertex drag), so this stays false whenever holes were never in
    // play for this gesture.
    const holesChanged =
      JSON.stringify(beforeHoles) !== JSON.stringify(m.holes);
    if (ptsChanged || holesChanged) {
      pushUndo({
        t: "measure-move",
        imageId,
        measureId: mid,
        before,
        after: m.pts,
        beforeHoles,
        afterHoles: m.holes,
      });
    }
    refresh(m);
  };

  /** Alt+edge-drag insert (step 3) — only for a closed ring with a real
   *  edge to grab NEAR the down-point (EDGE_INSERT_MAX_DIST_PX). Returns
   *  false when it does not apply — kind mismatch, or the down-point too
   *  far from every edge (e.g. deep in the interior) — so `onBodyDown`
   *  below can fall through to the plain translate. */
  const tryEdgeInsertDrag = (
    e: React.PointerEvent,
    m: Measure,
    screenPts: { x: number; y: number }[],
  ): boolean => {
    if (!e.altKey) return false;
    if (m.kind !== "polygon" && m.kind !== "lasso") return false;
    if (!svgRef.current || screenPts.length < 2) return false;

    const r = svgRef.current.getBoundingClientRect();
    const down = { x: e.clientX - r.left, y: e.clientY - r.top };
    const n = screenPts.length;
    let bestI = 0;
    let bestDist = Infinity;
    let bestProj = screenPts[0];
    for (let i = 0; i < n; i++) {
      // implicit closing edge (last -> first), same ring convention as
      // ClosedShapeGlyph's <polygon>/ringPath
      const { proj, dist } = projectToSegment(down, screenPts[i], screenPts[(i + 1) % n]);
      if (dist < bestDist) {
        bestDist = dist;
        bestI = i;
        bestProj = proj;
      }
    }

    // Reject a down-point too far from any edge (see EDGE_INSERT_MAX_DIST_PX)
    // — returning false here lets onBodyDown's caller fall through to the
    // plain whole-body translate below, same as any other non-qualifying
    // alt+drag.
    if (bestDist > EDGE_INSERT_MAX_DIST_PX) return false;

    const ip = screenToImage(bestProj.x, bestProj.y, view, img, vp);
    const nx = Math.min(1, Math.max(0, ip.x / img.w));
    const ny = Math.min(1, Math.max(0, ip.y / img.h));
    const insertAt = bestI + 1;
    const before = m.pts;
    const after = [
      ...before.slice(0, insertAt),
      { x: nx, y: ny },
      ...before.slice(insertAt),
    ];

    e.stopPropagation();
    updateMeasure(imageId, m.id, after);
    setSelected(m.id);
    // `pt: insertAt` arms onHandleMove's per-vertex branch (not the -1
    // body-translate branch), so the freshly-inserted point drags exactly
    // like any other handle for the rest of this gesture. beforeHoles is
    // snapshotted for the same reason as onHandleDown's — insert+drag
    // never touches holes, but onHandleUp's comparison needs a real value.
    dragRef.current = { mid: m.id, pt: insertAt, before, beforeHoles: m.holes };
    (e.target as Element).setPointerCapture(e.pointerId);
    return true;
  };

  const onBodyDown = (
    e: React.PointerEvent,
    m: Measure,
    screenPts: { x: number; y: number }[],
  ) => {
    if (tryEdgeInsertDrag(e, m, screenPts)) return;
    // plain whole-body translate (audit #12) — holes0/beforeHoles snapshot
    // the pre-drag holes so onHandleMove can shift them by the same delta
    // as pts and onHandleUp can tell whether they actually moved
    // (holes-detach fix).
    e.stopPropagation();
    setSelected(m.id);
    dragRef.current = {
      mid: m.id,
      pt: -1,
      before: m.pts,
      beforeHoles: m.holes,
      startX: e.clientX,
      startY: e.clientY,
      pts0: m.pts,
      holes0: m.holes,
    };
    (e.target as Element).setPointerCapture(e.pointerId);
  };

  const onVertexContextMenu = (
    e: React.MouseEvent,
    mid: string,
    vertexIndex: number,
  ) => {
    setSelected(mid);
    openMenu(e, mid, vertexIndex);
  };

  return {
    onHandleDown,
    onHandleMove,
    onHandleUp,
    onBodyDown,
    onVertexContextMenu,
  };
}

export interface VertexHandlesProps {
  pts: { x: number; y: number }[]; // screen-space
  mid: string;
  sel: boolean;
  color: string;
  kind: Measure["kind"];
  defaultEndSymbol: EndSymbol;
  endSymbol?: EndSymbol; // per-measure override (Measure.endSymbol)
  onHandleDown: (e: React.PointerEvent, mid: string, pt: number) => void;
  onHandleMove: (e: React.PointerEvent) => void;
  onHandleUp: (e: React.PointerEvent) => void;
  /** Right-click on a handle: records WHICH vertex, for the "Delete
   *  vertex" context-menu item (polygon/lasso only — MeasureCtxMenu.tsx
   *  gates on the target measure's kind and vertex count). */
  onVertexContextMenu?: (
    e: React.MouseEvent,
    mid: string,
    vertexIndex: number,
  ) => void;
}

/** Endpoint/vertex handle glyphs for one measure — verbatim behaviour
 *  extracted from MeasureOverlay's renderMeasure. */
export function VertexHandles({
  pts,
  mid,
  sel,
  color,
  kind,
  defaultEndSymbol,
  endSymbol,
  onHandleDown,
  onHandleMove,
  onHandleUp,
  onVertexContextMenu,
}: VertexHandlesProps) {
  return (
    <>
      {pts.map((p, i) => {
        // adjacent-segment direction for the perpendicular bar glyph
        const nb = pts.length > 1 ? (i === 0 ? pts[1] : pts[i - 1]) : null;
        const ang = nb ? Math.atan2(nb.y - p.y, nb.x - p.x) : 0;
        return (
          <g
            key={i}
            pointerEvents="all"
            style={{ cursor: "move" }}
            onPointerDown={(e) => onHandleDown(e, mid, i)}
            onPointerMove={onHandleMove}
            onPointerUp={onHandleUp}
            onContextMenu={
              onVertexContextMenu
                ? (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    onVertexContextMenu(e, mid, i);
                  }
                : undefined
            }
          >
            {(kind === "polygon" || kind === "lasso") ? (
              <>
                <circle
                  cx={p.x}
                  cy={p.y}
                  r={3}
                  fill="var(--surface-0)"
                  stroke={sel ? "var(--accent)" : color}
                  strokeWidth={1.5}
                />
                {/* transparent hit target — always present for drag capture */}
                <circle cx={p.x} cy={p.y} r={8} fill="transparent" stroke="none" />
              </>
            ) : (
              <EndpointGlyph
                cx={p.x}
                cy={p.y}
                sym={endSymbol ?? defaultEndSymbol}
                stroke={sel ? "var(--accent)" : color}
                angle={ang}
              />
            )}
          </g>
        );
      })}
    </>
  );
}
