// Filled + stroked closed path shared by the polygon and lasso measure
// kinds — split out of MeasureOverlay.tsx (plan item 14) to stay under
// the frontend size ratchet. One component covers both the in-progress
// preview (open-ish outline that auto-closes back to the first vertex —
// a free "here's where it'll close" hint) and the finalized, filled
// measure; the fill itself is the click/drag target when finalized, so
// unlike the thin line kinds this needs no separate fat-stroke hit twin.

import { polygonStats } from "../../lib/geometry";

/** Screen-space anchor for the area label — reuses the shoelace centroid
 *  (item 12): degenerate/zero-area input falls back to the plain vertex
 *  average rather than dividing by zero, so this is never NaN. */
export function closedShapeLabelAnchor(
  screenPts: { x: number; y: number }[],
): { x: number; y: number } {
  return polygonStats(screenPts).centroid;
}

export interface ClosedShapeGlyphProps {
  pts: { x: number; y: number }[]; // screen-space vertices
  /** Enclosed hole rings (plan item 4), screen-space — already run
   *  through the same image->screen transform as `pts`. Undefined/empty
   *  is the pre-item-4 shape: renders as the original plain <polygon>,
   *  byte-identical markup, so nothing that queries for it regresses. */
  holes?: { x: number; y: number }[][];
  stroke: string;
  strokeWidth: number;
  isPending: boolean;
  onBodyDown?: (e: React.PointerEvent) => void;
  onHandleMove?: (e: React.PointerEvent) => void;
  onHandleUp?: (e: React.PointerEvent) => void;
  onContextMenu?: (e: React.MouseEvent) => void;
  /** Discoverability hint for the alt-drag-to-insert gesture (lasso-editing
   *  plan, item D step 3) — omitted while pending, same as the handlers. */
  title?: string;
}

/** One closed subpath ("M x,y L x,y … Z") for the evenodd `d` string. */
function ringPath(pts: { x: number; y: number }[]): string {
  if (pts.length === 0) return "";
  const [first, ...rest] = pts;
  return `M ${first.x} ${first.y} ${rest.map((p) => `L ${p.x} ${p.y}`).join(" ")} Z`;
}

export function ClosedShapeGlyph({
  pts,
  holes,
  stroke,
  strokeWidth,
  isPending,
  onBodyDown,
  onHandleMove,
  onHandleUp,
  onContextMenu,
  title,
}: ClosedShapeGlyphProps) {
  const shared = {
    stroke,
    strokeWidth,
    strokeDasharray: isPending ? "6 4" : undefined,
    fillOpacity: isPending ? undefined : 0.18,
    pointerEvents: (isPending ? "none" : "all") as "none" | "all",
    style: { cursor: isPending ? "default" : "move" },
    onPointerDown: isPending ? undefined : onBodyDown,
    onPointerMove: isPending ? undefined : onHandleMove,
    onPointerUp: isPending ? undefined : onHandleUp,
    onContextMenu: isPending ? undefined : onContextMenu,
    title: isPending ? undefined : title,
  };
  // A hole reads as a VOID rather than a second overlapping shape via a
  // second <path> subpath + fill-rule evenodd (the conventional SVG way
  // to punch a hole), instead of drawing the outer ring and the hole as
  // two separate <polygon>s. Only reached once a region actually has
  // holes — the no-holes case below is untouched.
  if (holes && holes.length > 0) {
    const d = [ringPath(pts), ...holes.map(ringPath)].join(" ");
    return (
      <path
        d={d}
        fillRule="evenodd"
        fill={isPending ? "none" : stroke}
        {...shared}
      />
    );
  }
  return (
    <polygon
      points={pts.map((p) => `${p.x},${p.y}`).join(" ")}
      fill={isPending ? "none" : stroke}
      {...shared}
    />
  );
}
