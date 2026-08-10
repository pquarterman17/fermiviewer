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
  stroke: string;
  strokeWidth: number;
  isPending: boolean;
  onBodyDown?: (e: React.PointerEvent) => void;
  onHandleMove?: (e: React.PointerEvent) => void;
  onHandleUp?: (e: React.PointerEvent) => void;
  onContextMenu?: (e: React.MouseEvent) => void;
}

export function ClosedShapeGlyph({
  pts,
  stroke,
  strokeWidth,
  isPending,
  onBodyDown,
  onHandleMove,
  onHandleUp,
  onContextMenu,
}: ClosedShapeGlyphProps) {
  return (
    <polygon
      points={pts.map((p) => `${p.x},${p.y}`).join(" ")}
      stroke={stroke}
      strokeWidth={strokeWidth}
      strokeDasharray={isPending ? "6 4" : undefined}
      fill={isPending ? "none" : stroke}
      fillOpacity={isPending ? undefined : 0.18}
      pointerEvents={isPending ? "none" : "all"}
      style={{ cursor: isPending ? "default" : "move" }}
      onPointerDown={isPending ? undefined : onBodyDown}
      onPointerMove={isPending ? undefined : onHandleMove}
      onPointerUp={isPending ? undefined : onHandleUp}
      onContextMenu={isPending ? undefined : onContextMenu}
    />
  );
}
