// Stage-level right-click context menu (item #38).
// Hit-test order: scale bar → measure/annotation → empty image area.
// The empty-area branch delegates to the radial capture ring AND adds
// a "Copy Image" shortcut entry. Scale-bar hits open a dedicated menu
// whose wired actions grow in item #33.

import { useViewer, type Measure } from "../../store/viewer";
import { exportImage } from "../../lib/api";
import { DEFAULT_DISPLAY } from "../../store/viewer";

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
      </div>
    </>
  );
}

// ── Empty-area context menu (radial ring trigger + Copy Image) ────────

interface EmptyCtxProps {
  x: number;
  y: number;
  onClose: () => void;
}

export function EmptyAreaCtxMenu({ x, y, onClose }: EmptyCtxProps) {
  const setRadial = useViewer((s) => s.setRadial);
  const activeId = useViewer((s) => s.activeId);
  const setStatus = useViewer((s) => s.setStatus);
  const display = useViewer((s) =>
    activeId ? (s.display[activeId] ?? DEFAULT_DISPLAY) : DEFAULT_DISPLAY,
  );

  const copyImage = () => {
    if (!activeId) return;
    const d = display;
    const cmap = d.invert && d.cmap === "gray" ? "invert" : d.cmap;
    exportImage(activeId, {
      format: "png",
      scale: 1,
      lo: d.lo,
      hi: d.hi,
      gamma: d.gamma,
      cmap,
      include: [],
    })
      .then(({ blob }) =>
        navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]),
      )
      .then(() => setStatus("copied image to clipboard"))
      .catch((e: Error) => setStatus(`clipboard: ${e.message}`));
  };

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
            onClose();
            setRadial({ x, y });
          }}
        >
          Capture tools…
        </button>
        <div className="fvd-ctx-sep" />
        <button
          className="fvd-ctx-item"
          disabled={!activeId}
          onClick={() => {
            copyImage();
            onClose();
          }}
        >
          Copy Image
        </button>
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
