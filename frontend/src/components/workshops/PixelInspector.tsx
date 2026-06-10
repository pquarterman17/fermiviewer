// Pixel inspector (checklist N): live N×N grid of raw intensities
// around the cursor — ImageJ-style value magnifier. Reads the same
// client-side raster that drives the GL stage, so it costs no requests.

import { useState } from "react";

import { loadPrefs } from "../../lib/prefs";
import { rasterValue, useStageInfo } from "../../store/stage";
import { useViewer } from "../../store/viewer";

/** Grid is N×N, centre = cursor. Pref-driven (D13), clamped odd 3–15. */
function gridSize(): number {
  const n = Math.round(loadPrefs().inspectorGrid);
  return Math.min(15, Math.max(3, n)) | 1;
}

function cell(v: number | null): string {
  if (v === null) return "·";
  const a = Math.abs(v);
  if (a !== 0 && (a < 0.01 || a >= 1e5)) return v.toExponential(1);
  return Number(v.toPrecision(4)).toString();
}

export default function PixelInspector() {
  // read once per mount — reopening the window picks up a pref change
  const [N] = useState(gridSize);
  const HALF = Math.floor(N / 2);
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  const cursor = useStageInfo((s) => s.cursor);
  const raster = useStageInfo((s) => s.raster);

  if (!meta || meta.kind === "spectrum") {
    return <div className="fvd-ws-empty">Select a 2D image.</div>;
  }
  if (!cursor || !raster) {
    return <div className="fvd-ws-empty">Hover the image…</div>;
  }

  const cx = Math.floor(cursor.x);
  const cy = Math.floor(cursor.y);
  const rows = Array.from({ length: N }, (_, j) => cy - HALF + j);
  const cols = Array.from({ length: N }, (_, i) => cx - HALF + i);
  const centre = rasterValue(raster, cx, cy);

  return (
    <div className="fvd-ws">
      <div className="fvd-ws-note">
        ({cx}, {cy}) = {cell(centre)}
        {meta.pixel_size != null &&
          ` · ${Number((cx * meta.pixel_size).toPrecision(4))}, ` +
            `${Number((cy * meta.pixel_size).toPrecision(4))} ${meta.pixel_unit}`}
      </div>
      <table className="fvd-pixel-grid">
        <tbody>
          {rows.map((y) => (
            <tr key={y}>
              {cols.map((x) => (
                <td
                  key={x}
                  className={x === cx && y === cy ? "centre" : undefined}
                >
                  {cell(rasterValue(raster, x, y))}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
