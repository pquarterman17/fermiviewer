// ROI Manager card (Inspector, Tier-2 #5).
//
// Matches the MATLAB buildROIManager.m behaviour:
//   • lists named ROIs per image (name, geometry, stats when available)
//   • "Save current ROI as…" prompts for a name and stores the active
//     roi/ellipse measure in the per-image named-ROI list
//   • clicking a saved entry recalls (re-draws) it as the active measure
//   • × deletes an entry from the list
//
// Deviation from MATLAB: the MATLAB version is a separate modal dialog;
// here it is an inspector card so it stays in context.  The CSV export
// button is intentionally omitted — the existing "Measurement log / CSV"
// in MeasurePanel covers that path once the ROI is recalled.

import { useState } from "react";

import {
  useViewer,
  type Measure,
  type SavedRoi,
} from "../../store/viewer";
import Card from "./Card";

// stable fallback — never return a fresh [] inside a selector
const NO_MEASURES: Measure[] = [];
const NO_SAVED: SavedRoi[] = [];

function fmtPts(roi: SavedRoi): string {
  if (roi.pts.length < 2) return "—";
  const [a, b] = roi.pts;
  return `[${(a.x * 100).toFixed(0)}%,${(a.y * 100).toFixed(0)}% → ${(b.x * 100).toFixed(0)}%,${(b.y * 100).toFixed(0)}%]`;
}

export default function RoiManagerCard() {
  const activeId = useViewer((s) => s.activeId);
  const measures = useViewer((s) =>
    s.activeId ? (s.measures[s.activeId] ?? NO_MEASURES) : NO_MEASURES,
  );
  const roiStats = useViewer((s) => s.roiStats);
  const savedRois = useViewer((s) =>
    s.activeId ? (s.savedRois[s.activeId] ?? NO_SAVED) : NO_SAVED,
  );
  const selectedMeasure = useViewer((s) => s.selectedMeasure);
  const saveRoi = useViewer((s) => s.saveRoi);
  const recallRoi = useViewer((s) => s.recallRoi);
  const deleteRoi = useViewer((s) => s.deleteRoi);
  const setStatus = useViewer((s) => s.setStatus);

  const [nameInput, setNameInput] = useState("");

  if (!activeId) return null;

  // the currently selected measure if it is an roi/ellipse
  const activeMeasure = measures.find(
    (m) =>
      m.id === selectedMeasure &&
      (m.kind === "roi" || m.kind === "ellipse"),
  ) ?? null;

  const onSave = () => {
    if (!activeMeasure) {
      setStatus("ROI Manager: draw and select an ROI or ellipse first");
      return;
    }
    const name = nameInput.trim() ||
      `ROI ${savedRois.length + 1}`;
    saveRoi(activeId, name, {
      kind: activeMeasure.kind as "roi" | "ellipse",
      pts: activeMeasure.pts,
    });
    setNameInput("");
    setStatus(`saved ROI "${name}"`);
  };

  return (
    <Card title="ROI Manager" count={savedRois.length} defaultOpen={false}>
      <div className="fvd-ws-note">
        Draw an ROI or ellipse on the image, select it in the Measurements
        card, then save it here under a name to recall it later.
      </div>

      {/* Save row */}
      <div className="fvd-slider-row" style={{ gap: 4 }}>
        <input
          style={{ flex: 1, minWidth: 0 }}
          value={nameInput}
          placeholder={
            activeMeasure
              ? `Name (default: ROI ${savedRois.length + 1})`
              : "Select an ROI/ellipse first"
          }
          disabled={!activeMeasure}
          onChange={(e) => setNameInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") onSave();
          }}
        />
        <button
          className="fvd-btn"
          disabled={!activeMeasure}
          title={
            activeMeasure
              ? "Save the selected ROI/ellipse under this name"
              : "No roi/ellipse selected"
          }
          onClick={onSave}
        >
          Save
        </button>
      </div>

      {/* Saved list */}
      {savedRois.length === 0 ? (
        <div className="fvd-ws-note" style={{ color: "var(--fvd-muted)" }}>
          No saved ROIs yet.
        </div>
      ) : (
        <div className="fvd-measure-list" style={{ marginTop: 4 }}>
          {savedRois.map((roi) => {
            // find stats from a recalled measure with the same pts (best-effort)
            const matched = measures.find(
              (m) =>
                (m.kind === "roi" || m.kind === "ellipse") &&
                m.pts.length >= 2 &&
                roi.pts.length >= 2 &&
                Math.abs(m.pts[0].x - roi.pts[0].x) < 0.001 &&
                Math.abs(m.pts[0].y - roi.pts[0].y) < 0.001,
            );
            const stats = matched ? roiStats[matched.id] : undefined;

            return (
              <div
                key={roi.id}
                className="fvd-measure-row"
                title={`Recall "${roi.name}" (${roi.kind}, ${fmtPts(roi)})\nSaved ${new Date(roi.createdAt).toLocaleString()}`}
                style={{ cursor: "pointer" }}
                onClick={() => {
                  recallRoi(activeId, roi.id);
                  setStatus(`recalled ROI "${roi.name}"`);
                }}
              >
                <span className="glyph">
                  {roi.kind === "ellipse" ? "◯" : "▭"}
                </span>
                <span className="name" style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {roi.name}
                </span>
                {stats && (
                  <span
                    className="val"
                    style={{ fontSize: "0.78em", opacity: 0.75 }}
                    title={`mean ${stats.mean.toPrecision(4)}, std ${stats.std.toPrecision(3)}`}
                  >
                    {`μ${Number(stats.mean.toPrecision(3))}`}
                  </span>
                )}
                <button
                  className="fvd-icon-btn"
                  title={`Delete "${roi.name}"`}
                  onClick={(e) => {
                    e.stopPropagation();
                    deleteRoi(activeId, roi.id);
                    setStatus(`deleted ROI "${roi.name}"`);
                  }}
                >
                  ✕
                </button>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}
