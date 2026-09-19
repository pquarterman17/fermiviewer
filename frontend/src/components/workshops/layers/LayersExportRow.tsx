// What you do with a finished layer stack: take the numbers away, take
// the picture away, or keep the run.
//
// Split out of `LayersWorkshop.tsx` for the size guard, the three kept
// together because they are one decision — how this result leaves the
// workshop.
//
// "Export figure" is the micrograph itself, with the interfaces as the
// operator left them, the analysed region and the layer thicknesses
// burned in.
//
// The CSV exports say what was measured; this says WHERE, which is the
// part a reader of a paper cannot check from a table. It renders through
// the ordinary `/api/export` measurement path, so the figure inherits the
// display window, colormap and scale bar already on screen and cannot
// drift from them.

import { useState } from "react";

import { exportImage, type ExportOptions, type LayersResult } from "../../../lib/api";
import { layersFigureMeasures } from "../../../lib/layersFigure";
import { exportCsv } from "./LayerStack";
import type { AnalysisRoi } from "../../../hooks/useAnalysisRoi";
import { DEFAULT_DISPLAY, OVERLAY_FONT_PX, useViewer } from "../../../store/viewer";

function download(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function LayersFigureButton({
  result,
  roi,
  disabled,
  onError,
}: {
  result: LayersResult;
  roi: AnalysisRoi | null;
  disabled: boolean;
  onError: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const overlay = useViewer((s) => s.layersOverlay);

  // The figure is of the image the stack was measured ON, not of whatever
  // is active now: the overlay carries its own imageId, and exporting the
  // active one would silently draw one specimen's interfaces over another.
  const sourceId = overlay?.imageId ?? null;

  const run = async () => {
    const s = useViewer.getState();
    const meta = sourceId ? s.images[sourceId] : null;
    if (!overlay || !sourceId || !meta || meta.kind === "spectrum") return;
    const [h, w] = meta.shape;
    if (!Number.isFinite(h) || !Number.isFinite(w)) return;

    const display = s.display[sourceId] ?? DEFAULT_DISPLAY;
    const include = ["measurements"];
    if (meta.pixel_size !== null) include.push("scale_bar");
    const options: ExportOptions = {
      format: "png",
      scale: 2,
      lo: display.lo,
      hi: display.hi,
      gamma: display.gamma,
      // a client-local custom colormap has no server-side twin
      cmap: display.cmap === "custom" ? "gray" : display.cmap,
      include,
      measures: layersFigureMeasures(overlay, result, { h, w }, roi),
      overlay_color: s.overlay.color,
      overlay_font_size: OVERLAY_FONT_PX[s.overlay.size],
      overlay_line_width: s.overlay.lineWidth ?? 2.5,
    };
    setBusy(true);
    try {
      const { blob, filename } = await exportImage(sourceId, options);
      download(blob, filename);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <button
      className="fvd-btn"
      disabled={disabled || busy || !overlay}
      onClick={() => void run()}
      title="Export the image with the interfaces, region and thicknesses drawn on it"
    >
      {busy ? "Exporting…" : "Export figure"}
    </button>
  );
}

export function LayersExportRow({
  result,
  roi,
  disabled,
  saveResult,
  onSaveResult,
  onError,
}: {
  result: LayersResult;
  roi: AnalysisRoi | null;
  /** the quality gate: a run rated poor and not accepted exports nothing */
  disabled: boolean;
  saveResult: boolean;
  onSaveResult: (on: boolean) => void;
  onError: (message: string) => void;
}) {
  return (
    <div className="fvd-ws-row">
      <button
        className="fvd-btn"
        disabled={disabled}
        onClick={() => exportCsv(result)}
        title="Export layers + interfaces as CSV"
      >
        Export CSV
      </button>
      <LayersFigureButton
        result={result}
        roi={roi}
        disabled={disabled}
        onError={onError}
      />
      <label
        className="fvd-check"
        title="Keep this run, its settings, the layer table and the depth profile it was measured from in Results & Methods"
      >
        <input
          type="checkbox"
          checked={saveResult}
          onChange={(e) => onSaveResult(e.target.checked)}
        />
        Save result
      </label>
    </div>
  );
}
