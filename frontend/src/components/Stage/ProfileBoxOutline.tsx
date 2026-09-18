// The averaging BOX a box profile integrates over, and the handles that
// resize it.
//
// Split out of MeasureOverlay.tsx when the width handles pushed that module
// past the 500-line guard. It is one cohesive idea — a profile's other
// dimension, and the only gesture that reaches it — so it moves as a unit.
//
// **What the endpoint handles already do, and what this adds.** A box
// profile is stored as a two-point line plus a perpendicular averaging
// `width`, and the backend samples along that line at ANY angle
// (`calc.profiles.line_profile`, bilinear). So dragging either endpoint
// already changes both the length and the DIRECTION of integration —
// rotation was never missing, only invisible. What no handle could reach was
// the width: it was fixed at creation from the drawn box's short side and
// editable afterwards only through a numeric field that sets the default for
// the NEXT capture.
//
// Both long edges move together, keeping the box centred on its line. An
// asymmetric box would still integrate, but the profile would no longer be
// centred on the feature the user drew the line through, and nothing in the
// result would say so.

import { useRef } from "react";

import { imageToScreen, type Size } from "../../lib/geometry";
import type { Measure, View } from "../../store/viewerTypes";

export interface ProfileBoxOutlineProps {
  measure: Measure;
  /** perpendicular averaging width, image pixels */
  width: number;
  /** the line's two endpoints, already in screen space */
  pts: { x: number; y: number }[];
  view: View;
  img: Size;
  vp: Size;
  imageId: string;
  color: string;
  selected: boolean;
  /** stroke/opacity props the rest of the overlay shares */
  common: Record<string, unknown>;
  svgRef: React.RefObject<SVGSVGElement | null>;
  setSelected: (id: string) => void;
  setMeasureWidth: (imageId: string, measureId: string, width: number) => void;
  /** re-run the analysis: a new width is new numbers, the same reason a
      moved endpoint refreshes on release */
  onWidthCommitted: () => void;
}

export default function ProfileBoxOutline({
  measure,
  width,
  pts,
  view,
  img,
  vp,
  imageId,
  color,
  selected,
  common,
  svgRef,
  setSelected,
  setMeasureWidth,
  onWidthCommitted,
}: ProfileBoxOutlineProps) {
  const dragging = useRef(false);

  // screen px per image px (uniform zoom)
  const o = imageToScreen(0, 0, view, img, vp);
  const u = imageToScreen(1, 0, view, img, vp);
  const pxScale = Math.hypot(u.x - o.x, u.y - o.y);
  const ang = Math.atan2(pts[1].y - pts[0].y, pts[1].x - pts[0].x);
  const half = (width / 2) * pxScale;
  const ox = -Math.sin(ang) * half;
  const oy = Math.cos(ang) * half;
  const mx = (pts[0].x + pts[1].x) / 2;
  const my = (pts[0].y + pts[1].y) / 2;

  const widthFromPointer = (e: React.PointerEvent): number => {
    const r = svgRef.current?.getBoundingClientRect();
    const sx = e.clientX - (r?.left ?? 0);
    const sy = e.clientY - (r?.top ?? 0);
    // perpendicular distance from the centreline, doubled: the drag moves
    // one edge and the box is symmetric, so the width is twice it
    const perp = Math.abs(
      -Math.sin(ang) * (sx - mx) + Math.cos(ang) * (sy - my),
    );
    return (2 * perp) / (pxScale || 1);
  };

  const grip = (sign: 1 | -1) => (
    <g
      key={sign}
      pointerEvents="all"
      style={{ cursor: "move" }}
      onPointerDown={(e) => {
        e.stopPropagation();
        // optional-call to match the guarded release below: not every element
        // in every environment implements pointer capture, and losing the
        // capture degrades the drag rather than breaking the handler
        (e.target as Element).setPointerCapture?.(e.pointerId);
        dragging.current = true;
        setSelected(measure.id);
      }}
      onPointerMove={(e) => {
        if (!dragging.current) return;
        setMeasureWidth(imageId, measure.id, widthFromPointer(e));
      }}
      onPointerUp={(e) => {
        if (!dragging.current) return;
        dragging.current = false;
        (e.target as Element).releasePointerCapture?.(e.pointerId);
        onWidthCommitted();
      }}
    >
      {/* fat transparent edge: the grab target is the whole long side, not
          just the dot, so the gesture works without hunting for a handle */}
      <line
        x1={pts[0].x + sign * ox}
        y1={pts[0].y + sign * oy}
        x2={pts[1].x + sign * ox}
        y2={pts[1].y + sign * oy}
        stroke="transparent"
        strokeWidth={10}
        pointerEvents="stroke"
      />
      <circle
        cx={mx + sign * ox}
        cy={my + sign * oy}
        r={3.5}
        fill="var(--surface-0)"
        stroke={color}
        strokeWidth={1.5}
      />
    </g>
  );

  return (
    <>
      <polygon
        points={
          `${pts[0].x + ox},${pts[0].y + oy} ${pts[1].x + ox},${pts[1].y + oy} ` +
          `${pts[1].x - ox},${pts[1].y - oy} ${pts[0].x - ox},${pts[0].y - oy}`
        }
        {...common}
      />
      {selected && (
        <>
          {grip(1)}
          {grip(-1)}
        </>
      )}
    </>
  );
}
