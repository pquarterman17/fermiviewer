import { applyGeometry, cropToRoi } from "../../lib/stageOps";
import { useStageInfo } from "../../store/stage";
import { useViewer } from "../../store/viewer";

export function FloatTools() {
  const activeId = useViewer((s) => s.activeId);
  const captureMode = useViewer((s) => s.captureMode);
  const setCaptureMode = useViewer((s) => s.setCaptureMode);
  const panTool = useViewer((s) => s.panTool);
  const setPanTool = useViewer((s) => s.setPanTool);
  const deleteLastAnnotation = useViewer((s) => s.deleteLastAnnotation);
  const resetToOriginal = useViewer((s) => s.resetToOriginal);
  const startSideBySide = useViewer((s) => s.startSideBySide);
  const canCompare = useViewer((s) => s.order.length >= 2);
  const hasMeasures = useViewer((s) =>
    activeId ? (s.measures[activeId] ?? []).length > 0 : false,
  );
  const isDerived = useViewer((s) =>
    activeId
      ? typeof s.images[activeId]?.meta["derived_from"] === "string"
      : false,
  );

  const mode = (m: typeof captureMode) => () =>
    setCaptureMode(captureMode === m ? "none" : m);

  const transforms: [string, string, () => void][] = [
    ["⟲", "Rotate 90° CCW", () => applyGeometry("rotate270")],
    ["⟳", "Rotate 90° CW", () => applyGeometry("rotate90")],
    ["⬌", "Flip horizontal", () => applyGeometry("fliph")],
    ["⬍", "Flip vertical", () => applyGeometry("flipv")],
  ];
  const tools: [string, string, boolean, () => void][] = [
    ["✥", "Hand tool  H", panTool, () => setPanTool(!panTool)],
    ["⬚", "Box zoom  Z", captureMode === "zoom", mode("zoom")],
    ["⊞", "Fixed Size Zoom  F", captureMode === "fixed-zoom", mode("fixed-zoom")],
    ["↔", "Distance  D", captureMode === "distance", mode("distance")],
    ["∿", "Line profile  L", captureMode === "profile", mode("profile")],
    ["⧈", "Box profile (integrated)  B", captureMode === "box-profile", mode("box-profile")],
    ["⌇", "Polyline  P", captureMode === "polyline", mode("polyline")],
    ["∠", "Angle  G", captureMode === "angle", mode("angle")],
    ["▭", "ROI stats  R", captureMode === "roi", mode("roi")],
    ["📏", "Calibrate scale", captureMode === "calibrate", mode("calibrate")],
  ];

  const splitTip = (s: string): [string, string | null] => {
    const match = /^(.*?)\s{2,}(\S.*)$/.exec(s);
    return match ? [match[1], match[2]] : [s, null];
  };

  return (
    <div
      className="fvd-glass fvd-float-tools"
      role="toolbar"
      aria-label="Image and measurement tools"
      onPointerDown={(e) => e.stopPropagation()}
    >
      {transforms.map(([glyph, title, onClick]) => {
        const [label, hint] = splitTip(title);
        return (
          <button
            key={title}
            className="fvd-tool-btn"
            aria-label={label}
            data-tip={label}
            data-tip-key={hint ?? undefined}
            onClick={onClick}
          >
            {glyph}
          </button>
        );
      })}
      <span className="fvd-tool-sep" aria-hidden="true" />
      {tools.map(([glyph, title, active, onClick]) => {
        const [label, hint] = splitTip(title);
        return (
          <button
            key={title}
            className={`fvd-tool-btn${active ? " active" : ""}`}
            aria-label={label}
            aria-pressed={active}
            data-tip={label}
            data-tip-key={hint ?? undefined}
            onClick={onClick}
          >
            {glyph}
          </button>
        );
      })}
      <span className="fvd-tool-sep" aria-hidden="true" />
      <button
        className="fvd-tool-btn"
        aria-label="Crop to ROI"
        data-tip="Crop to ROI"
        onClick={() => cropToRoi()}
      >
        ✂
      </button>
      <button
        className={`fvd-tool-btn${captureMode === "crop-save" ? " active" : ""}`}
        aria-label="Save cropped region"
        aria-pressed={captureMode === "crop-save"}
        data-tip="Save Cropped Region"
        onClick={mode("crop-save")}
      >
        ⊡
      </button>
      <span className="fvd-tool-sep" aria-hidden="true" />
      <button
        className="fvd-tool-btn"
        aria-label="Side-by-side compare"
        data-tip="Side-by-side compare"
        disabled={!canCompare}
        onClick={() => startSideBySide()}
      >
        ◫
      </button>
      <span className="fvd-tool-sep" aria-hidden="true" />
      {hasMeasures && (
        <button
          className="fvd-tool-btn"
          aria-label="Delete last annotation"
          data-tip="Delete last annotation"
          onClick={() => {
            if (activeId) deleteLastAnnotation(activeId);
          }}
        >
          ⌫
        </button>
      )}
      {isDerived && (
        <button
          className="fvd-tool-btn"
          aria-label="Reset to original pixels"
          data-tip="Reset to original pixels"
          onClick={() => {
            if (activeId) resetToOriginal(activeId);
          }}
        >
          ⟳₀
        </button>
      )}
    </div>
  );
}

export function ZoomChip({ onZoom }: { onZoom: (factor: number) => void }) {
  const zoom = useStageInfo((s) => s.zoom);
  if (zoom === null) return null;
  return (
    <div className="fvd-glass fvd-zoom-chip">
      <button
        className="fvd-icon-btn"
        aria-label="Zoom out"
        data-tip="Zoom out"
        onClick={() => onZoom(0.8)}
      >
        ⊖
      </button>
      <span>{Math.round(zoom * 100)} %</span>
      <button
        className="fvd-icon-btn"
        aria-label="Zoom in"
        data-tip="Zoom in"
        onClick={() => onZoom(1.25)}
      >
        ⊕
      </button>
    </div>
  );
}
