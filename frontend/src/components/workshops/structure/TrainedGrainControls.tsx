// Trained-grains controls, split out of StructureWorkshop.tsx (repo-health
// #33). Moved verbatim; only imports now point one directory up.

import type { GrainPreview } from "../../../lib/api";
import { SCRIBBLE_COLORS, useScribble } from "../../../store/scribble";
import { TrainedGrainPreview } from "../TrainedGrainPreview";
import { paintedReadyCount } from "./GrainsMode";

// Trained-mode controls: pick a class, set the brush, paint examples on the
// stage, then train+segment. A class can be flagged as boundary/background
// (∅) so its pixels are excluded from grains.
export function TrainedGrainControls({
  numClasses,
  classId,
  brush,
  boundary,
  nStrokes,
  minArea,
  setMinArea,
  classifier,
  setClassifier,
  busy,
  progress,
  onRun,
  onPreview,
  previewBusy,
  preview,
  activeId,
  sourceId,
  showPreview,
}: {
  numClasses: number;
  classId: number;
  brush: number;
  boundary: number[];
  nStrokes: number;
  minArea: string;
  setMinArea: (v: string) => void;
  classifier: "softmax" | "forest";
  setClassifier: (v: "softmax" | "forest") => void;
  busy: boolean;
  progress: string;
  onRun: () => void;
  onPreview: () => void;
  previewBusy: boolean;
  preview: GrainPreview | null;
  activeId: string;
  sourceId: string;
  showPreview: (id: string) => void;
}) {
  const setClass = useScribble((s) => s.setClass);
  const setNumClasses = useScribble((s) => s.setNumClasses);
  const setBrush = useScribble((s) => s.setBrush);
  const toggleBoundary = useScribble((s) => s.toggleBoundary);
  const clear = useScribble((s) => s.clear);
  // live painted-state (the design's ✓/○ chips): which classes have at least
  // one stroke, and how many non-boundary classes are painted (≥2 to train).
  // Read the stroke array by reference — no fresh-array selector, so no
  // re-render churn.
  const strokes = useScribble((s) => s.strokes);
  const painted = new Set(strokes.map((s) => s.classId));
  const readyCount = paintedReadyCount(strokes, boundary);

  return (
    <>
      <div className="fvd-ws-row">
        <span className="k">classes</span>
        <div style={{ display: "flex", gap: 4, flex: 1, flexWrap: "wrap" }}>
          {Array.from({ length: numClasses }, (_, i) => i + 1).map((c) => {
            const col = SCRIBBLE_COLORS[(c - 1) % SCRIBBLE_COLORS.length];
            const isBnd = boundary.includes(c);
            return (
              <button
                key={c}
                className="fvd-btn"
                title={
                  (isBnd ? "boundary/background class" : `class ${c}`) +
                  (painted.has(c) ? " · painted" : " · not painted yet")
                }
                onClick={() => setClass(c)}
                style={{
                  minWidth: 26,
                  padding: "2px 6px",
                  background: col,
                  color: "#111",
                  outline: classId === c ? "2px solid #fff" : "none",
                  opacity: isBnd ? 0.5 : 1,
                }}
              >
                {isBnd ? "∅" : c}
                {painted.has(c) && (
                  <span style={{ marginLeft: 3, fontSize: 9 }}>✓</span>
                )}
              </button>
            );
          })}
        </div>
        <button
          className="fvd-btn"
          title="fewer classes"
          onClick={() => setNumClasses(numClasses - 1)}
        >
          −
        </button>
        <button
          className="fvd-btn"
          title="more classes"
          onClick={() => setNumClasses(numClasses + 1)}
        >
          +
        </button>
      </div>
      <div className="fvd-ws-row">
        <span className="k">brush</span>
        <input
          type="range"
          min={1}
          max={40}
          value={brush}
          style={{ flex: 1 }}
          onChange={(e) => setBrush(Number(e.target.value))}
        />
        <span style={{ width: 28, textAlign: "right" }}>{brush}px</span>
        <button
          className="fvd-btn"
          title="mark the current class as boundary/background"
          onClick={() => toggleBoundary(classId)}
          style={{
            outline: boundary.includes(classId) ? "2px solid #fff" : "none",
          }}
        >
          ∅
        </button>
      </div>
      <div className="fvd-ws-row">
        <span className="k">model</span>
        <select
          value={classifier}
          style={{ flex: 1 }}
          title="Forest learns nonlinear texture boundaries; softmax is a faster linear model"
          onChange={(e) =>
            setClassifier(e.target.value as "softmax" | "forest")
          }
        >
          <option value="forest">Random forest — nonlinear</option>
          <option value="softmax">Softmax — linear, fast</option>
        </select>
      </div>
      <div className="fvd-ws-row">
        <span className="k">min area</span>
        <input
          value={minArea}
          style={{ width: 44 }}
          onChange={(e) => setMinArea(e.target.value)}
        />
        <span style={{ flex: 1 }} />
        <button
          className="fvd-btn"
          style={{ flex: "0 0 auto", padding: "4px 10px" }}
          onClick={clear}
          disabled={nStrokes === 0}
          title="Clear all painted training strokes"
        >
          Clear
        </button>
      </div>
      <div className="fvd-ws-row">
        <button
          className="fvd-btn"
          title="Preview the pixel classification (per-class %) without committing to grains"
          onClick={onPreview}
          disabled={previewBusy || busy || nStrokes === 0}
        >
          {previewBusy ? "Previewing…" : "Preview"}
        </button>
        <button
          className="fvd-btn primary"
          onClick={onRun}
          disabled={busy || previewBusy || nStrokes === 0}
          title="Train the classifier on your strokes, then segment grains"
        >
          {busy ? progress || "Training…" : "Train & segment"}
        </button>
      </div>
      {preview && (
        <TrainedGrainPreview
          preview={preview}
          activeId={activeId}
          sourceId={sourceId}
          show={showPreview}
        />
      )}
      <div
        className="fvd-ws-note"
        style={{ color: readyCount >= 2 ? "var(--capture)" : undefined }}
      >
        {readyCount >= 2
          ? `${readyCount} classes painted · ready to train & segment`
          : `paint ${2 - readyCount} more class${
              2 - readyCount === 1 ? "" : "es"
            } to train`}
      </div>
      <div className="fvd-ws-note">
        Paint a few strokes of each class on the image, then train. ∅ marks a
        class as boundary/background (excluded from grains).
      </div>
    </>
  );
}
