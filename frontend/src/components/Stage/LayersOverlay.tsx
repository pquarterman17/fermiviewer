// Stage overlay for the Cross-section Layers workshop: draws the detected
// interface mean-lines (and the wavy σ_w trace) on the image. When the
// workshop's "Edit on stage" mode is on, interfaces become interactive —
// drag to nudge, click empty space to add, right-click to remove. Edits are
// published to `layersEditReq`; the workshop owns the recompute + params.
//
// Interfaces are drawn at the stack's tilt, and a handle at the end of the
// topmost line rotates the WHOLE stack. One angle, not one per interface:
// layers in a film stack are parallel, so per-interface angles would let two
// of them cross and leave "depth" with no single meaning to measure a
// thickness along. The tilt goes out on its own channel (`layersTiltReq`)
// because changing it re-collapses the profile, and the interface positions
// are depths IN that profile — so a moved line and a new angle cannot be
// applied in the same step.

import { useRef, useState } from "react";

import { imageToScreen, screenToImage, type Size } from "../../lib/geometry";
import { useViewer, type View } from "../../store/viewer";

export default function LayersOverlay({
  imageId,
  view,
  img,
  vp,
}: {
  imageId: string;
  view: View;
  img: Size;
  vp: Size;
}) {
  const overlay = useViewer((s) => s.layersOverlay);
  const edit = useViewer((s) => s.layersEdit);
  const setLayersOverlay = useViewer((s) => s.setLayersOverlay);
  const setLayersEditReq = useViewer((s) => s.setLayersEditReq);
  const setLayersTiltReq = useViewer((s) => s.setLayersTiltReq);
  const setLayersFocusReq = useViewer((s) => s.setLayersFocusReq);
  const svgRef = useRef<SVGSVGElement>(null);
  const [drag, setDrag] = useState<{ index: number; pos: number } | null>(null);
  const [tiltDrag, setTiltDrag] = useState<number | null>(null);

  if (!overlay || overlay.imageId !== imageId) return null;
  const horizontal = overlay.axis === "y";
  const positions = overlay.interfaces;
  const tilt = tiltDrag ?? overlay.tiltDeg ?? 0;
  const theta = (tilt * Math.PI) / 180;

  // pointer (window) → image depth along the growth axis
  const depthAt = (clientX: number, clientY: number): number => {
    const rect = svgRef.current?.getBoundingClientRect();
    const p = screenToImage(
      clientX - (rect?.left ?? 0),
      clientY - (rect?.top ?? 0),
      view,
      img,
      vp,
    );
    return horizontal ? p.y : p.x;
  };

  const clampDepth = (value: number) => overlay.depthRange
    ? Math.min(overlay.depthRange[1], Math.max(overlay.depthRange[0], value))
    : value;
  const commit = (next: number[]) => setLayersEditReq(next.map(clampDepth));

  const onLineDown = (e: React.PointerEvent, k: number) => {
    if (!edit) return;
    e.stopPropagation();
    (e.target as Element).setPointerCapture(e.pointerId);
    setDrag({ index: k, pos: positions[k] });
  };
  const onMove = (e: React.PointerEvent) => {
    if (!drag) return;
    setDrag({ index: drag.index, pos: clampDepth(depthAt(e.clientX, e.clientY)) });
  };
  const onUp = (e: React.PointerEvent) => {
    if (!drag) return;
    const next = positions.map((p, i) => (i === drag.index ? drag.pos : p));
    // optimistic: move the line now, the workshop's recompute refines it
    setLayersOverlay({ ...overlay, interfaces: next });
    commit(next);
    setDrag(null);
    (e.target as Element).releasePointerCapture?.(e.pointerId);
  };

  const lineFor = (k: number) => (drag?.index === k ? drag.pos : positions[k]);

  // ── the shared tilt handle ──────────────────────────────────────────
  // Anchored at the FIRST interface's far end. Dragging it swings that end
  // about the stack's lateral midpoint; the angle that lands is the one the
  // whole stack is re-collapsed along.
  const lateralLo = overlay.lateralRange?.[0] ?? 0;
  const lateralHi = overlay.lateralRange?.[1] ?? (horizontal ? img.w : img.h);
  const halfSpan = Math.max((lateralHi - lateralLo) / 2, 1);

  const tiltFromPointer = (clientX: number, clientY: number): number => {
    const rect = svgRef.current?.getBoundingClientRect();
    const p = screenToImage(
      clientX - (rect?.left ?? 0),
      clientY - (rect?.top ?? 0),
      view,
      img,
      vp,
    );
    const depth = horizontal ? p.y : p.x;
    const anchor = positions.length ? lineFor(0) : 0;
    // atan of rise-over-run from the pivot, clamped: past ~60 deg the
    // inscribed sampling box has almost nothing left, and the backend
    // refuses rather than returning a one-pixel-wide "average".
    const deg = (Math.atan2(depth - anchor, halfSpan) * 180) / Math.PI;
    return Math.max(-60, Math.min(60, deg));
  };
  const onTiltDown = (e: React.PointerEvent) => {
    e.stopPropagation();
    (e.target as Element).setPointerCapture(e.pointerId);
    setTiltDrag(tilt);
  };
  const onTiltMove = (e: React.PointerEvent) => {
    if (tiltDrag === null) return;
    setTiltDrag(tiltFromPointer(e.clientX, e.clientY));
  };
  const onTiltUp = (e: React.PointerEvent) => {
    if (tiltDrag === null) return;
    setLayersOverlay({ ...overlay, tiltDeg: tiltDrag });
    setLayersTiltReq(tiltDrag);
    setTiltDrag(null);
    (e.target as Element).releasePointerCapture?.(e.pointerId);
  };

  return (
    <svg
      ref={svgRef}
      className="fvd-measure-layer"
      width={vp.w}
      height={vp.h}
      style={{ pointerEvents: edit ? "auto" : "none" }}
      onPointerMove={(e) => {
        onMove(e);
        onTiltMove(e);
      }}
      onPointerUp={(e) => {
        onUp(e);
        onTiltUp(e);
      }}
    >
      {/* click-to-add background (edit mode only) */}
      {edit && (
        <rect
          x={0}
          y={0}
          width={vp.w}
          height={vp.h}
          fill="transparent"
          onClick={(e) => commit([...positions, depthAt(e.clientX, e.clientY)])}
        />
      )}
      {positions.map((_pos, k) => {
        const pos = lineFor(k);
        const lateral0 = lateralLo;
        const lateral1 = lateralHi;
        // Rotate each line about the lateral midpoint so raising the tilt
        // pivots the stack in place rather than sweeping it off the region.
        const depthAtLateral = (lateral: number) =>
          pos + (lateral - (lateralLo + lateralHi) / 2) * Math.tan(theta);
        const a = horizontal
          ? imageToScreen(lateral0, depthAtLateral(lateral0), view, img, vp)
          : imageToScreen(depthAtLateral(lateral0), lateral0, view, img, vp);
        const b = horizontal
          ? imageToScreen(lateral1, depthAtLateral(lateral1), view, img, vp)
          : imageToScreen(depthAtLateral(lateral1), lateral1, view, img, vp);
        const trace = overlay.traces[k];
        const poly =
          trace && drag?.index !== k
            ? trace
                .map((d, j) => {
                  const lateral = j + (overlay.lateralOffset ?? 0);
                  const p = horizontal
                    ? imageToScreen(lateral, d, view, img, vp)
                    : imageToScreen(d, lateral, view, img, vp);
                  return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
                })
                .join(" ")
            : null;
        return (
          <g key={k}>
            {poly && (
              <polyline points={poly} fill="none" stroke="#22d3ee" strokeWidth={1} opacity={0.8} />
            )}
            <line
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              stroke="#f59e0b"
              strokeWidth={drag?.index === k ? 1.6 : 1}
              strokeDasharray="5 3"
              opacity={0.9}
            />
            {/* fat transparent hit line. Edit mode: drag to nudge, right-click
                to remove. Otherwise: click focuses this interface's roughness
                detail card in the workshop (pointerEvents re-enabled per-line
                so the rest of the stage still pans/zooms). */}
            <line
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              stroke="transparent"
              strokeWidth={12}
              style={{
                cursor: edit ? (horizontal ? "ns-resize" : "ew-resize") : "pointer",
                pointerEvents: "stroke",
              }}
              onPointerDown={(e) => onLineDown(e, k)}
              onClick={() => {
                if (!edit) setLayersFocusReq(k);
              }}
              onContextMenu={(e) => {
                if (!edit) return;
                e.preventDefault();
                e.stopPropagation();
                commit(positions.filter((_, i) => i !== k));
              }}
            />
          </g>
        );
      })}
      {edit && positions.length > 0 && (() => {
        const anchor = lineFor(0);
        const end = anchor + halfSpan * Math.tan(theta);
        const p = horizontal
          ? imageToScreen(lateralHi, end, view, img, vp)
          : imageToScreen(end, lateralHi, view, img, vp);
        return (
          <g>
            <circle
              cx={p.x}
              cy={p.y}
              r={5}
              fill="#f59e0b"
              stroke="#0b0f14"
              strokeWidth={1.5}
              opacity={0.95}
            />
            {/* a larger invisible target: a 5 px dot is hard to grab at low
                zoom, the same reason MeasureVertexLayer pairs every vertex
                glyph with a fatter hit circle */}
            <circle
              cx={p.x}
              cy={p.y}
              r={12}
              fill="transparent"
              style={{ cursor: "grab", pointerEvents: "all" }}
              onPointerDown={onTiltDown}
            >
              <title>
                Drag to tilt the whole stack; the profile is re-integrated
                along the new axis
              </title>
            </circle>
            {tiltDrag !== null && (
              <text
                x={p.x + 14}
                y={p.y - 8}
                fill="#f59e0b"
                fontSize={12}
                style={{ pointerEvents: "none" }}
              >
                {tiltDrag.toFixed(1)}°
              </text>
            )}
          </g>
        );
      })()}
    </svg>
  );
}
