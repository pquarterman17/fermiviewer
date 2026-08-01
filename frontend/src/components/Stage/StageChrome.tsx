// Small sibling components rendered alongside the Stage canvas, split out
// in the repo-health #33 decomposition of Stage.tsx. Moved verbatim.

import { useState } from "react";

import { rasterValue, useStageInfo } from "../../store/stage";
import { useViewer } from "../../store/viewer";
import type { Pt } from "./stageUtils";

export function GrainEditBar({
  mode,
  setMode,
  pending,
}: {
  mode: "off" | "merge" | "split";
  setMode: (m: "off" | "merge" | "split") => void;
  pending: Pt | null;
}) {
  const hint =
    mode === "merge"
      ? pending
        ? "click the 2nd grain"
        : "click the 1st grain"
      : mode === "split"
        ? "click a grain to split"
        : "";
  return (
    <div
      className="fvd-glass fvd-grain-edit"
      onPointerDown={(e) => e.stopPropagation()}
    >
      <span className="lbl">Grains</span>
      <div className="fvd-seg">
        <button
          className={`fvd-seg-btn${mode === "merge" ? " active" : ""}`}
          aria-pressed={mode === "merge"}
          title="Merge — click two grains"
          onClick={() => setMode(mode === "merge" ? "off" : "merge")}
        >
          Merge
        </button>
        <button
          className={`fvd-seg-btn${mode === "split" ? " active" : ""}`}
          aria-pressed={mode === "split"}
          title="Split — click a grain"
          onClick={() => setMode(mode === "split" ? "off" : "split")}
        >
          Split
        </button>
      </div>
      {hint && <span className="hint">{hint}</span>}
    </div>
  );
}

export function Readout() {
  const cursor = useStageInfo((s) => s.cursor);
  const raster = useStageInfo((s) => s.raster);
  if (!cursor) return null;
  const v = rasterValue(raster, cursor.x, cursor.y);
  return (
    <div className="fvd-glass fvd-readout">
      {Math.floor(cursor.x)}, {Math.floor(cursor.y)}
      {v !== null && ` · ${Number(v.toPrecision(5))}`}
    </div>
  );
}

// ── Fixed-size zoom badge (item #41 A2) ──────────────────────────────

export function FixedZoomBadge({ w, h }: { w: number; h: number }) {
  const setFixedZoomDims = useViewer((s) => s.setFixedZoomDims);
  const setCaptureMode = useViewer((s) => s.setCaptureMode);
  const [wStr, setWStr] = useState(String(w));
  const [hStr, setHStr] = useState(String(h));

  const apply = () => {
    const nw = Math.max(1, parseInt(wStr) || w);
    const nh = Math.max(1, parseInt(hStr) || h);
    setFixedZoomDims(nw, nh);
  };

  return (
    <div className="fvd-glass fvd-fixed-zoom-badge">
      <span>Fixed Zoom</span>
      <input
        value={wStr}
        style={{ width: 44 }}
        onChange={(e) => setWStr(e.target.value)}
        onBlur={apply}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            apply();
            e.stopPropagation();
          }
        }}
        placeholder="W"
        aria-label="Width in pixels"
      />
      <span>×</span>
      <input
        value={hStr}
        style={{ width: 44 }}
        onChange={(e) => setHStr(e.target.value)}
        onBlur={apply}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            apply();
            e.stopPropagation();
          }
        }}
        placeholder="H"
        aria-label="Height in pixels"
      />
      <span className="fvd-text-faint">px — click to place</span>
      <button
        className="fvd-icon-btn"
        aria-label="Cancel fixed zoom"
        title="Cancel"
        onClick={() => setCaptureMode("none")}
      >
        ✕
      </button>
    </div>
  );
}

// ── Stack frame stepper overlay (item #40 / D11) ─────────────────────

export function StackStepper({
  imageId: _imageId,
  frame,
  total,
  onStep,
}: {
  imageId: string;
  frame: number;
  total: number;
  onStep: (delta: number) => void;
}) {
  return (
    <div className="fvd-glass fvd-stack-stepper">
      <button
        className="fvd-icon-btn"
        aria-label="Previous frame"
        disabled={frame <= -1}
        onClick={(e) => {
          e.stopPropagation();
          onStep(-1);
        }}
        title="Previous frame  ,"
      >
        ◀
      </button>
      <span className="fvd-stack-label">
        {frame < 0 ? `Σ / ${total}` : `${frame + 1} / ${total}`}
      </span>
      <button
        className="fvd-icon-btn"
        aria-label="Next frame"
        disabled={frame >= total - 1}
        onClick={(e) => {
          e.stopPropagation();
          onStep(1);
        }}
        title="Next frame  ."
      >
        ▶
      </button>
    </div>
  );
}
