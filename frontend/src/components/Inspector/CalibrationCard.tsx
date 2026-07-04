// Calibration inspector card: manual pixel-size calibration from a drawn
// distance line (for images with a baked-in scale bar but no metadata).
// Draw a distance across a known length (the 📏 Calibrate tool snaps H/V),
// enter its real length here, and the pixel size is set — the line then
// disappears and the scale bar appears. Clear resets to uncalibrated pixels.

import { useState } from "react";

import { applyCalibration, clearCalibration } from "../../lib/api";
import { useViewer, type Measure } from "../../store/viewer";
import Card from "./Card";

const UNITS = ["nm", "µm", "Å", "pm", "mm"] as const;

// stable empty snapshot (zustand React #185 — never return a fresh [])
const NO_MEASURES: Measure[] = [];

export default function CalibrationCard() {
  const activeId = useViewer((s) => s.activeId);
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  const measures = useViewer((s) =>
    s.activeId ? (s.measures[s.activeId] ?? NO_MEASURES) : NO_MEASURES,
  );
  const selectedId = useViewer((s) => s.selectedMeasure);
  const removeMeasure = useViewer((s) => s.removeMeasure);
  const setStatus = useViewer((s) => s.setStatus);
  const setCaptureMode = useViewer((s) => s.setCaptureMode);

  const [len, setLen] = useState("");
  const [unit, setUnit] = useState<(typeof UNITS)[number]>("nm");
  const [busy, setBusy] = useState(false);

  if (!meta || !activeId) return null;

  // the calibration line: the SELECTED distance, else the last distance drawn
  const distances = measures.filter((m) => m.kind === "distance");
  const line =
    distances.find((m) => m.id === selectedId) ?? distances.at(-1) ?? null;

  const [h, w] = meta.shape;
  const lenPx = line
    ? Math.hypot(
        (line.pts[1].x - line.pts[0].x) * w,
        (line.pts[1].y - line.pts[0].y) * h,
      )
    : 0;

  const lenVal = Number(len);
  const canCalibrate =
    !!line && lenPx > 0 && Number.isFinite(lenVal) && lenVal > 0;
  const previewPx = canCalibrate ? lenVal / lenPx : null;

  const calibrate = () => {
    if (!canCalibrate || !line) return;
    setBusy(true);
    applyCalibration(activeId, lenVal / lenPx, unit)
      .then((r) => {
        useViewer.setState((s) => ({
          images: { ...s.images, [r.image.id]: r.image },
        }));
        removeMeasure(activeId, line.id); // the calibration line disappears
        setStatus(
          `calibrated: ${r.image.pixel_size?.toPrecision(4)} ` +
            `${r.image.pixel_unit}/px`,
        );
        setLen("");
      })
      .catch((e: Error) => setStatus(`calibrate: ${e.message}`))
      .finally(() => setBusy(false));
  };

  const clear = () => {
    setBusy(true);
    clearCalibration(activeId)
      .then((r) => {
        useViewer.setState((s) => ({
          images: { ...s.images, [r.image.id]: r.image },
        }));
        setStatus("calibration cleared — uncalibrated (pixels)");
      })
      .catch((e: Error) => setStatus(`clear: ${e.message}`))
      .finally(() => setBusy(false));
  };

  return (
    <Card title="Calibration">
      <div className="fvd-meta-row">
        <span className="k">Pixel size</span>
        <span className="v">
          {meta.pixel_size != null
            ? `${meta.pixel_size.toPrecision(4)} ${meta.pixel_unit}/px`
            : "Uncalibrated"}
        </span>
      </div>

      <div className="fvd-meta-row">
        <span className="k">Calibration line</span>
        <span className="v">
          {line ? `${lenPx.toFixed(1)} px` : "none — draw a distance"}
        </span>
      </div>

      <div className="fvd-slider-row">
        <span className="k">Known length</span>
        <input
          type="number"
          style={{ width: 72 }}
          min={0}
          step="any"
          value={len}
          placeholder="e.g. 200"
          disabled={!line}
          onChange={(e) => setLen(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && canCalibrate) calibrate();
          }}
        />
        <select
          value={unit}
          disabled={!line}
          onChange={(e) => setUnit(e.target.value as (typeof UNITS)[number])}
        >
          {UNITS.map((u) => (
            <option key={u} value={u}>
              {u}
            </option>
          ))}
        </select>
      </div>

      {previewPx != null && (
        <div
          className="fvd-text-faint"
          style={{ fontSize: 11, marginBottom: 4 }}
        >
          → {previewPx.toPrecision(4)} {unit}/px
        </div>
      )}

      <div className="fvd-btn-row">
        {line ? (
          <button
            className="fvd-btn primary"
            disabled={!canCalibrate || busy}
            onClick={calibrate}
            title="Set pixel size from the drawn line and its known length"
          >
            Calibrate from line
          </button>
        ) : (
          <button
            className="fvd-btn primary"
            disabled={busy}
            title="Draw a line across a known length (snaps horizontal/vertical)"
            onClick={() => setCaptureMode("calibrate")}
          >
            📏 Draw calibration line
          </button>
        )}
        <button
          className="fvd-btn"
          disabled={busy || meta.pixel_size == null}
          title="Reset to uncalibrated pixels"
          onClick={clear}
        >
          Clear
        </button>
      </div>

      <div className="fvd-text-faint" style={{ fontSize: 11, marginTop: 4 }}>
        Draw a distance across a known length (e.g. a baked-in scale bar) with
        the 📏 tool, then set its real length here.
      </div>
    </Card>
  );
}
