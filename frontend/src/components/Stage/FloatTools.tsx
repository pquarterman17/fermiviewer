import { applyGeometry, cropToRoi } from "../../lib/stageOps";
import { useStageInfo } from "../../store/stage";
import { useViewer } from "../../store/viewer";
import Icon, { type IconName } from "../icons/Icon";

const TOOL_DETAIL: Record<string, string> = {
  "Hand tool": "Drag the image without changing pixels.",
  "Box zoom": "Drag a rectangle to magnify that region.",
  "Fixed Size Zoom": "Capture a region using the dimensions in Preferences.",
  Distance: "Drag between two points to measure calibrated length.",
  "Line profile": "Sample intensity along a line you place on the image.",
  "Box profile (integrated)": "Integrate intensity across a rectangular selection.",
  Polyline: "Click multiple points to measure a segmented path.",
  Angle: "Click three points to measure the included angle.",
  "ROI stats": "Drag a region to calculate statistics and a histogram.",
  "Calibrate scale": "Draw over a known distance, then enter its physical length.",
};

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

  const transforms: [IconName, string, () => void][] = [
    ["rotate-ccw", "Rotate 90° CCW", () => applyGeometry("rotate270")],
    ["rotate-cw", "Rotate 90° CW", () => applyGeometry("rotate90")],
    ["flip-horizontal", "Flip horizontal", () => applyGeometry("fliph")],
    ["flip-vertical", "Flip vertical", () => applyGeometry("flipv")],
  ];
  const tools: [IconName, string, boolean, () => void][] = [
    ["hand", "Hand tool  H", panTool, () => setPanTool(!panTool)],
    ["box-zoom", "Box zoom  Z", captureMode === "zoom", mode("zoom")],
    ["fixed-zoom", "Fixed Size Zoom  F", captureMode === "fixed-zoom", mode("fixed-zoom")],
    ["distance", "Distance  D", captureMode === "distance", mode("distance")],
    ["profile", "Line profile  L", captureMode === "profile", mode("profile")],
    ["box-profile", "Box profile (integrated)  B", captureMode === "box-profile", mode("box-profile")],
    ["polyline", "Polyline  P", captureMode === "polyline", mode("polyline")],
    ["angle", "Angle  G", captureMode === "angle", mode("angle")],
    ["roi", "ROI stats  R", captureMode === "roi", mode("roi")],
    ["ruler", "Calibrate scale", captureMode === "calibrate", mode("calibrate")],
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
      {transforms.map(([icon, title, onClick]) => {
        const [label, hint] = splitTip(title);
        return (
          <button
            key={title}
            className="fvd-tool-btn"
            aria-label={label}
            data-tip={label}
            data-tip-detail={TOOL_DETAIL[label]}
            data-tip-key={hint ?? undefined}
            onClick={onClick}
          >
            <Icon name={icon} />
          </button>
        );
      })}
      <span className="fvd-tool-sep" aria-hidden="true" />
      {tools.map(([icon, title, active, onClick]) => {
        const [label, hint] = splitTip(title);
        return (
          <button
            key={title}
            className={`fvd-tool-btn${active ? " active" : ""}`}
            aria-label={label}
            aria-pressed={active}
            data-tip={label}
            data-tip-detail={TOOL_DETAIL[label]}
            data-tip-key={hint ?? undefined}
            onClick={onClick}
          >
            <Icon name={icon} />
          </button>
        );
      })}
      <span className="fvd-tool-sep" aria-hidden="true" />
      <button
        className="fvd-tool-btn"
        aria-label="Crop to ROI"
        data-tip="Crop to ROI"
        data-tip-detail="Create a derived image from the most recent ROI."
        onClick={() => cropToRoi()}
      >
        <Icon name="crop" />
      </button>
      <button
        className={`fvd-tool-btn${captureMode === "crop-save" ? " active" : ""}`}
        aria-label="Save cropped region"
        aria-pressed={captureMode === "crop-save"}
        data-tip="Save Cropped Region"
        data-tip-detail="Drag a region and save it as a new derived image."
        onClick={mode("crop-save")}
      >
        <Icon name="save-crop" />
      </button>
      <span className="fvd-tool-sep" aria-hidden="true" />
      <button
        className="fvd-tool-btn"
        aria-label="Side-by-side compare"
        data-tip="Side-by-side compare"
        data-tip-detail="Open loaded images in linked panes for visual comparison."
        disabled={!canCompare}
        onClick={() => startSideBySide()}
      >
        <Icon name="compare" />
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
          <Icon name="delete" />
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
          <Icon name="reset" />
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
        <Icon name="zoom-out" />
      </button>
      <span>{Math.round(zoom * 100)} %</span>
      <button
        className="fvd-icon-btn"
        aria-label="Zoom in"
        data-tip="Zoom in"
        onClick={() => onZoom(1.25)}
      >
        <Icon name="zoom-in" />
      </button>
    </div>
  );
}
