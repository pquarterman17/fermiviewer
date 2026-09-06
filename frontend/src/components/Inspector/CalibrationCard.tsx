// Calibration inspector card: manual pixel-size calibration from a drawn
// distance line (for images with a baked-in scale bar but no metadata).
// Draw a distance across a known length (the 📏 Calibrate tool snaps H/V),
// enter its real length here, and the pixel size is set — the line then
// disappears and the scale bar appears. Clear resets to uncalibrated pixels.

import { useEffect, useState } from "react";

import {
  applyCalibration,
  applyCalibrationAxes,
  clearCalibration,
} from "../../lib/api";
import { useViewer, type Measure } from "../../store/viewer";
import Card from "./Card";
import {
  calibrationLineAxis,
  formatExtent,
  positiveNumber,
} from "./calibrationUi";

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
  const [rowExtent, setRowExtent] = useState("");
  const [columnExtent, setColumnExtent] = useState("");
  const [unit, setUnit] = useState<(typeof UNITS)[number]>("nm");
  const [mode, setMode] = useState<"square" | "per-axis">("square");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const spacing = meta?.pixel_spacing;
    const fallback = meta?.pixel_size;
    setRowExtent(spacing ? String(spacing[0]) : fallback != null ? String(fallback) : "");
    setColumnExtent(spacing ? String(spacing[1]) : fallback != null ? String(fallback) : "");
    if (meta?.pixel_unit && UNITS.includes(meta.pixel_unit as (typeof UNITS)[number])) {
      setUnit(meta.pixel_unit as (typeof UNITS)[number]);
    }
  }, [activeId, meta?.pixel_size, meta?.pixel_spacing, meta?.pixel_unit]);

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
  const canSquareCalibrate =
    !!line && lenPx > 0 && Number.isFinite(lenVal) && lenVal > 0;
  const squarePreview = canSquareCalibrate ? lenVal / lenPx : null;
  const lineAxis = calibrationLineAxis(line, meta.shape);
  const lineAxisPreview =
    lineAxis && Number.isFinite(lenVal) && lenVal > 0
      ? lenVal / lineAxis.pixels
      : null;
  const rowValue = positiveNumber(rowExtent);
  const columnValue = positiveNumber(columnExtent);
  const canApplyPair = rowValue != null && columnValue != null;
  const canAxisCalibrate =
    lineAxisPreview != null &&
    (lineAxis?.axis === "row" ? columnValue != null : rowValue != null);

  const acceptImage = (image: typeof meta) => {
    useViewer.setState((s) => ({
      images: { ...s.images, [image.id]: image },
    }));
  };

  const calibrate = () => {
    if (!canSquareCalibrate || !line) return;
    setBusy(true);
    applyCalibration(activeId, lenVal / lenPx, unit)
      .then((r) => {
        acceptImage(r.image);
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

  const applyPair = (spacing: [number, number], removeLine = false) => {
    setBusy(true);
    applyCalibrationAxes(activeId, spacing, unit)
      .then((r) => {
        acceptImage(r.image);
        if (removeLine && line) removeMeasure(activeId, line.id);
        const applied = r.image.pixel_spacing ?? spacing;
        setStatus(
          `calibrated: rows ${formatExtent(applied[0])} · columns ` +
            `${formatExtent(applied[1])} ${r.image.pixel_unit}/px`,
        );
      })
      .catch((e: Error) => setStatus(`calibrate: ${e.message}`))
      .finally(() => setBusy(false));
  };

  const calibrateAxisFromLine = () => {
    if (!lineAxis || lineAxisPreview == null || !canAxisCalibrate) return;
    const spacing: [number, number] =
      lineAxis.axis === "row"
        ? [lineAxisPreview, columnValue as number]
        : [rowValue as number, lineAxisPreview];
    applyPair(spacing, true);
  };

  const clear = () => {
    setBusy(true);
    clearCalibration(activeId)
      .then((r) => {
        acceptImage(r.image);
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

      {meta.pixel_spacing && meta.pixel_spacing[0] !== meta.pixel_spacing[1] && (
        <div className="fvd-calibration-extents" role="status">
          <span>Rows {formatExtent(meta.pixel_spacing[0])}</span>
          <span>Columns {formatExtent(meta.pixel_spacing[1])}</span>
          <span>{meta.pixel_unit}/px</span>
        </div>
      )}

      <div className="fvd-seg fvd-seg-wide" aria-label="Pixel geometry">
        {(["square", "per-axis"] as const).map((choice) => (
          <button
            key={choice}
            className={`fvd-seg-btn${mode === choice ? " active" : ""}`}
            aria-pressed={mode === choice}
            onClick={() => setMode(choice)}
          >
            {choice === "square" ? "Square pixels" : "Per axis"}
          </button>
        ))}
      </div>

      {mode === "per-axis" && (
        <div className="fvd-calibration-pair">
          <label>
            <span>Row extent</span>
            <input
              aria-label="Row pixel extent"
              type="number"
              min={0}
              step="any"
              value={rowExtent}
              onChange={(e) => setRowExtent(e.target.value)}
            />
          </label>
          <label>
            <span>Column extent</span>
            <input
              aria-label="Column pixel extent"
              type="number"
              min={0}
              step="any"
              value={columnExtent}
              onChange={(e) => setColumnExtent(e.target.value)}
            />
          </label>
          <label>
            <span>Unit</span>
            <select
              aria-label="Pixel extent unit"
              value={unit}
              onChange={(e) => setUnit(e.target.value as (typeof UNITS)[number])}
            >
              {UNITS.map((u) => <option key={u}>{u}</option>)}
            </select>
          </label>
          <button
            className="fvd-btn"
            disabled={!canApplyPair || busy}
            onClick={() => applyPair([rowValue as number, columnValue as number])}
          >
            Apply extents
          </button>
        </div>
      )}

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
            if (e.key !== "Enter") return;
            if (mode === "square" && canSquareCalibrate) calibrate();
            if (mode === "per-axis" && canAxisCalibrate) calibrateAxisFromLine();
          }}
        />
        {mode === "square" ? (
          <select
            value={unit}
            disabled={!line}
            aria-label="Known length unit"
            onChange={(e) => setUnit(e.target.value as (typeof UNITS)[number])}
          >
            {UNITS.map((u) => (
              <option key={u} value={u}>
                {u}
              </option>
            ))}
          </select>
        ) : (
          <span className="fvd-text-faint">{unit}</span>
        )}
      </div>

      {mode === "square" && squarePreview != null && (
        <div
          className="fvd-text-faint"
          style={{ fontSize: 11, marginBottom: 4 }}
        >
          → {squarePreview.toPrecision(4)} {unit}/px on both axes
        </div>
      )}

      {mode === "per-axis" && line && !lineAxis && (
        <div className="fvd-callout warn" role="alert">
          Per-axis calibration needs a horizontal or vertical line. This line
          is diagonal; redraw it within 15° of an axis.
        </div>
      )}

      {mode === "per-axis" && lineAxis && lineAxisPreview != null && (
        <div className="fvd-text-faint" style={{ fontSize: 11, marginBottom: 4 }}>
          → {lineAxis.axis === "row" ? "row" : "column"} extent{" "}
          {formatExtent(lineAxisPreview)} {unit}/px; other axis unchanged
        </div>
      )}

      {mode === "per-axis" && lineAxisPreview != null && !canAxisCalibrate && (
        <div className="fvd-callout" role="status">
          Enter the other axis extent before applying this line.
        </div>
      )}

      <div className="fvd-btn-row">
        {line ? (
          <button
            className="fvd-btn primary"
            disabled={
              busy ||
              (mode === "square" ? !canSquareCalibrate : !canAxisCalibrate)
            }
            onClick={mode === "square" ? calibrate : calibrateAxisFromLine}
            title={
              mode === "square"
                ? "Set square pixel size from the drawn line"
                : "Set the matching axis while preserving the other extent"
            }
          >
            {mode === "square"
              ? "Calibrate from line"
              : `Calibrate ${lineAxis?.axis ?? "axis"} from line`}
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
        {mode === "square"
          ? "Draw across a known length, then enter its real length."
          : "Use separate extents, or draw horizontally for columns and vertically for rows."}
      </div>
    </Card>
  );
}
