// Export dialog (handoff §4 "Export"): format · resolution · includes,
// live output dims + size estimate → POST /export → browser download.

import { useState } from "react";

import { exportImage, type ExportOptions } from "../../lib/api";
import { DEFAULT_DISPLAY, useViewer, type Measure } from "../../store/viewer";

type Format = ExportOptions["format"];

const FORMATS: { key: Format; label: string }[] = [
  { key: "png", label: "PNG" },
  { key: "tiff16", label: "TIFF-16" },
  { key: "jpeg", label: "JPEG" },
  { key: "svg", label: "SVG" },
  { key: "pdf", label: "PDF" },
];

// rough compressed-size factors vs raw bytes (estimate only)
const SIZE_FACTOR: Record<Format, number> = {
  png: 0.5,
  tiff16: 1.0,
  jpeg: 0.15,
  svg: 0.7, // base64 PNG payload
  pdf: 0.5,
};

// stable empty snapshot (zustand React #185 — never return a fresh [])
const NO_MEASURES: Measure[] = [];

export default function ExportDialog() {
  const open = useViewer((s) => s.exportOpen);
  const setOpen = useViewer((s) => s.setExportOpen);
  const activeId = useViewer((s) => s.activeId);
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  const display = useViewer((s) =>
    s.activeId ? (s.display[s.activeId] ?? DEFAULT_DISPLAY) : DEFAULT_DISPLAY,
  );
  const setStatus = useViewer((s) => s.setStatus);
  const measures = useViewer((s) =>
    s.activeId ? (s.measures[s.activeId] ?? NO_MEASURES) : NO_MEASURES,
  );
  const overlayColor = useViewer((s) => s.overlay.color);

  const [format, setFormat] = useState<Format>("png");
  const [scale, setScale] = useState(1);
  const [scaleBar, setScaleBar] = useState(true);
  const [bakeMeasures, setBakeMeasures] = useState(true);
  const [busy, setBusy] = useState(false);

  if (!open) return null;
  if (!activeId || !meta || meta.kind === "spectrum") {
    return (
      <div className="fvd-overlay-backdrop" onMouseDown={() => setOpen(false)}>
        <div
          className="fvd-glass fvd-export"
          onMouseDown={(e) => e.stopPropagation()}
        >
          <h2>Export</h2>
          <div className="fvd-ws-empty">No exportable image selected.</div>
        </div>
      </div>
    );
  }

  const h = meta.shape[0] * scale;
  const w = meta.shape[1] * scale;
  const bytesPerPx = format === "tiff16" ? 2 : 3;
  const estBytes = w * h * bytesPerPx * SIZE_FACTOR[format];
  const canBar = format !== "tiff16" && meta.pixel_size !== null;
  const canMeasure = format !== "tiff16" && measures.length > 0;

  const run = () => {
    setBusy(true);
    const include: string[] = [];
    if (canBar && scaleBar) include.push("scale_bar");
    if (canMeasure && bakeMeasures) include.push("measurements");
    exportImage(activeId, {
      format,
      scale,
      lo: display.lo,
      hi: display.hi,
      gamma: display.gamma,
      cmap: display.cmap,
      include,
      measures:
        canMeasure && bakeMeasures
          ? measures.map((m) => ({ kind: m.kind, pts: m.pts }))
          : undefined,
      overlay_color: overlayColor,
    })
      .then(({ blob, filename }) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
        setStatus(`exported ${filename}`);
        setOpen(false);
      })
      .catch((e: Error) => setStatus(`export: ${e.message}`))
      .finally(() => setBusy(false));
  };

  return (
    <div className="fvd-overlay-backdrop" onMouseDown={() => setOpen(false)}>
      <div
        className="fvd-glass fvd-export"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <h2>Export — {meta.name}</h2>

        <div className="fvd-ws-row">
          <span className="k">Format</span>
          <div className="fvd-seg">
            {FORMATS.map((f) => (
              <button
                key={f.key}
                className={`fvd-seg-btn${format === f.key ? " active" : ""}`}
                onClick={() => setFormat(f.key)}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>

        <div className="fvd-ws-row">
          <span className="k">Resolution</span>
          <div className="fvd-seg">
            {[1, 2, 3, 4].map((s) => (
              <button
                key={s}
                className={`fvd-seg-btn${scale === s ? " active" : ""}`}
                onClick={() => setScale(s)}
              >
                {s}×
              </button>
            ))}
          </div>
        </div>

        <div className="fvd-ws-row">
          <span className="k">Include</span>
          <label className={`fvd-check${canBar ? "" : " disabled"}`}>
            <input
              type="checkbox"
              checked={canBar && scaleBar}
              disabled={!canBar}
              onChange={(e) => setScaleBar(e.target.checked)}
            />
            Scale bar
          </label>
          <label className={`fvd-check${canMeasure ? "" : " disabled"}`}>
            <input
              type="checkbox"
              checked={canMeasure && bakeMeasures}
              disabled={!canMeasure}
              onChange={(e) => setBakeMeasures(e.target.checked)}
            />
            Measurements ({measures.length})
          </label>
        </div>

        <div className="fvd-export-info">
          {w} × {h} px · ~{fmtBytes(estBytes)}
          {format === "tiff16" && " · 16-bit grayscale (data export)"}
          {format === "svg" && " · vector overlays + embedded PNG"}
          {format === "pdf" && " · single-page raster PDF"}
        </div>

        <div className="fvd-btn-row">
          <button className="fvd-btn" onClick={() => setOpen(false)}>
            Cancel
          </button>
          <button className="fvd-btn primary" onClick={run} disabled={busy}>
            {busy ? "Exporting…" : "Export"}
          </button>
        </div>
      </div>
    </div>
  );
}

function fmtBytes(b: number): string {
  if (b >= 1e6) return `${(b / 1e6).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(b / 1e3))} kB`;
}
