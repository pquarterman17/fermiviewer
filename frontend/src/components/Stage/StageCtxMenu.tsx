// Stage-level right-click hit-testing + the scale-bar context menu.
// buildCtxTarget classifies a right-click as scale bar / measure / empty;
// Stage opens the radial capture ring for empty (and missed-measure)
// clicks, while scale-bar hits open this dedicated menu wired to
// hide/show + length/position controls (item #33).

import { niceScaleLength } from "../../lib/geometry";
import { useViewer, type Measure } from "../../store/viewer";

export interface CtxTarget {
  kind: "scalebar" | "measure" | "empty";
  /** for kind === "measure": the measure id */
  measureId?: string;
  x: number;
  y: number;
}

// ── Scale-bar context menu ────────────────────────────────────────────

interface ScaleBarCtxProps {
  x: number;
  y: number;
  onClose: () => void;
}

export function ScaleBarCtxMenu({ x, y, onClose }: ScaleBarCtxProps) {
  const toggleScaleBar = useViewer((s) => s.toggleScaleBar);
  const scaleBarVisible = useViewer((s) => s.scaleBarVisible);
  const activeId = useViewer((s) => s.activeId);
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  const setScaleBar = useViewer((s) => s.setScaleBar);

  const pixelSize = meta?.pixel_size ?? null;
  const unit = meta?.pixel_unit ?? "px";

  // compute a couple of nice presets relative to current zoom
  const presets: number[] =
    pixelSize != null
      ? [1, 2, 4].map((z) => niceScaleLength((120 * pixelSize) / z))
          .filter((v, i, a) => a.indexOf(v) === i)
      : [];

  return (
    <>
      <div
        className="fvd-ctx-backdrop"
        onPointerDown={onClose}
        onContextMenu={(e) => {
          e.preventDefault();
          onClose();
        }}
      />
      <div
        className="fvd-ctx-menu fvd-glass"
        style={{ left: x, top: y }}
        onPointerDown={(e) => e.stopPropagation()}
      >
        <button
          className="fvd-ctx-item"
          onClick={() => {
            toggleScaleBar();
            onClose();
          }}
        >
          {scaleBarVisible ? "Hide Scale Bar" : "Show Scale Bar"}
        </button>
        {activeId && pixelSize != null && presets.length > 0 && (
          <>
            <div className="fvd-ctx-sep" />
            <span className="fvd-ctx-label">Length</span>
            <button
              className="fvd-ctx-item"
              onClick={() => {
                setScaleBar(activeId, { lengthPhys: null });
                onClose();
              }}
            >
              Auto
            </button>
            {presets.map((p) => (
              <button
                key={p}
                className="fvd-ctx-item"
                onClick={() => {
                  setScaleBar(activeId, { lengthPhys: p });
                  onClose();
                }}
              >
                {p >= 1
                  ? `${Number(p.toPrecision(3))} ${unit}`
                  : `${Number((p * 1000).toPrecision(3))} p${unit}`}
              </button>
            ))}
          </>
        )}
        {activeId && (
          <>
            <div className="fvd-ctx-sep" />
            <button
              className="fvd-ctx-item"
              onClick={() => {
                setScaleBar(activeId, { x: 0.02, y: 0.92, lengthPhys: null, thickness: null, fontSize: null });
                onClose();
              }}
            >
              Reset position
            </button>
          </>
        )}
      </div>
    </>
  );
}

// ── Measure item context menu re-export (passes through to MeasureOverlay) ──

/**
 * Build the CtxTarget from a right-click event on the stage.
 * Caller supplies the element references needed for hit-testing.
 */
export function buildCtxTarget(
  e: React.MouseEvent,
  scaleBarEl: Element | null,
  measures: Measure[],
  img: { w: number; h: number } | null,
  view: { z: number; px: number; py: number } | null,
  vp: { w: number; h: number },
): CtxTarget {
  const x = e.clientX;
  const y = e.clientY;

  // 1. Scale bar hit — check if the click was inside the scale-bar div
  if (scaleBarEl) {
    const r = scaleBarEl.getBoundingClientRect();
    // expand hit target by 8px in each direction for easier clicking
    if (
      x >= r.left - 8 &&
      x <= r.right + 8 &&
      y >= r.top - 8 &&
      y <= r.bottom + 8
    ) {
      return { kind: "scalebar", x, y };
    }
  }

  // 2. Measure / annotation hit — check if the click is near a measure handle
  //    or label (coarse hit: within 12px of any endpoint in screen space)
  if (img && view) {
    const stageEl = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const sx = x - stageEl.left;
    const sy = y - stageEl.top;

    for (const m of measures) {
      for (const pt of m.pts) {
        // convert normalized point → screen
        const px = (pt.x - view.px) * view.z * img.w + vp.w / 2;
        const py = (pt.y - view.py) * view.z * img.h + vp.h / 2;
        const dist = Math.hypot(sx - px, sy - py);
        if (dist <= 12) {
          return { kind: "measure", measureId: m.id, x, y };
        }
      }
    }
  }

  // 3. Empty image area
  return { kind: "empty", x, y };
}
