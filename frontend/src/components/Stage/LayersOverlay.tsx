// Stage overlay for the Cross-section Layers workshop: draws the detected
// interface mean-lines (and the wavy σ_w trace) on the image. When the
// workshop's "Edit on stage" mode is on, interfaces become interactive —
// drag to nudge, click empty space to add, right-click to remove. Edits are
// published to `layersEditReq`; the workshop owns the recompute + params.

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
  const setLayersFocusReq = useViewer((s) => s.setLayersFocusReq);
  const svgRef = useRef<SVGSVGElement>(null);
  const [drag, setDrag] = useState<{ index: number; pos: number } | null>(null);

  if (!overlay || overlay.imageId !== imageId) return null;
  const horizontal = overlay.axis === "y";
  const positions = overlay.interfaces;

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

  return (
    <svg
      ref={svgRef}
      className="fvd-measure-layer"
      width={vp.w}
      height={vp.h}
      style={{ pointerEvents: edit ? "auto" : "none" }}
      onPointerMove={onMove}
      onPointerUp={onUp}
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
        const lateral0 = overlay.lateralRange?.[0] ?? 0;
        const lateral1 = overlay.lateralRange?.[1] ?? (horizontal ? img.w : img.h);
        const a = horizontal
          ? imageToScreen(lateral0, pos, view, img, vp)
          : imageToScreen(pos, lateral0, view, img, vp);
        const b = horizontal
          ? imageToScreen(lateral1, pos, view, img, vp)
          : imageToScreen(pos, lateral1, view, img, vp);
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
    </svg>
  );
}
