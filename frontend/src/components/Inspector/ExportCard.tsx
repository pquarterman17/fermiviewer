// Export inspector card (quick path): format + resolution + Export, with
// "More…" opening the full Export dialog for advanced options (LUT range,
// colormap, includes). Shares the export routine (lib/export) with that
// dialog so the quick and full paths behave identically.

import { useState } from "react";

import { type ExportOptions } from "../../lib/api";
import { exportActive } from "../../lib/export";
import { loadPrefs } from "../../lib/prefs";
import { useViewer } from "../../store/viewer";
import Card from "./Card";

type Format = ExportOptions["format"];

const FORMATS: { key: Format; label: string }[] = [
  { key: "png", label: "PNG" },
  { key: "tiff16", label: "TIFF-16" },
  { key: "jpeg", label: "JPEG" },
  { key: "svg", label: "SVG" },
  { key: "pdf", label: "PDF" },
];

export default function ExportCard() {
  const activeId = useViewer((s) => s.activeId);
  const setExportOpen = useViewer((s) => s.setExportOpen);
  const setStatus = useViewer((s) => s.setStatus);
  // seed from saved Export preferences (Preferences → Export)
  const [format, setFormat] = useState<Format>(() => loadPrefs().exportFormat);
  const [scale, setScale] = useState(() => loadPrefs().exportScale);
  const [busy, setBusy] = useState(false);

  if (!activeId) return null;

  const run = () => {
    setBusy(true);
    // honor the Preferences → Export include defaults (scale bar /
    // measurements / colorbar) so the quick path matches the full dialog
    const p = loadPrefs();
    exportActive({
      format,
      scale,
      scaleBar: p.exportScaleBar,
      measures: p.exportMeasures,
      colorbar: p.exportColorbar,
    })
      .then((filename) => setStatus(`exported ${filename}`))
      .catch((e: Error) => setStatus(`export: ${e.message}`))
      .finally(() => setBusy(false));
  };

  return (
    <Card title="Export" defaultOpen={false}>
      <div className="fvd-meta-row">
        <span className="k">Format</span>
        <select
          value={format}
          onChange={(e) => setFormat(e.target.value as Format)}
        >
          {FORMATS.map((f) => (
            <option key={f.key} value={f.key}>
              {f.label}
            </option>
          ))}
        </select>
      </div>
      <div className="fvd-meta-row">
        <span className="k">Resolution</span>
        <select
          value={scale}
          onChange={(e) => setScale(Number(e.target.value))}
        >
          {[1, 2, 3, 4].map((s) => (
            <option key={s} value={s}>
              {s}×
            </option>
          ))}
        </select>
      </div>
      <div className="fvd-btn-row">
        <button
          className="fvd-btn primary"
          onClick={run}
          disabled={busy}
          title="Export the active image in the chosen format and resolution"
        >
          {busy ? "Exporting…" : "Export"}
        </button>
        <button
          className="fvd-btn"
          title="Open the full Export dialog (LUT range, colormap, includes)"
          onClick={() => setExportOpen(true)}
        >
          More…
        </button>
      </div>
    </Card>
  );
}
