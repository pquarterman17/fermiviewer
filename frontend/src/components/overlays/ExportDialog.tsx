// Export / Report builder (handoff §4 "Export" + design WS4c): format ·
// resolution · includes · report caption, with a LIVE preview that bakes
// the same overlays the real export does, plus an "included" summary.

import { useEffect, useMemo, useRef, useState } from "react";

import { type ExportOptions } from "../../lib/api";
import { exportActive, previewActive } from "../../lib/export";
import { loadPrefs } from "../../lib/prefs";
import { useViewer, type Measure } from "../../store/viewer";

type Format = ExportOptions["format"];

const FORMATS: { key: Format; label: string }[] = [
  { key: "png", label: "PNG" },
  { key: "tiff16", label: "TIFF-16" },
  { key: "jpeg", label: "JPEG" },
  { key: "svg", label: "SVG" },
  { key: "pdf", label: "PDF" },
];

// journal single/double-column widths (mm) — the publication sizing presets
const JOURNAL_WIDTHS: { label: string; mm: number }[] = [
  { label: "Nature", mm: 89 },
  { label: "Nature 2-col", mm: 183 },
  { label: "Science", mm: 85 },
  { label: "ACS", mm: 84 },
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

/** Trim a float for the metadata line (0.5, not 0.5000). */
function fmtNum(v: number): string {
  return String(+v.toPrecision(4));
}

export default function ExportDialog() {
  const open = useViewer((s) => s.exportOpen);
  const setOpen = useViewer((s) => s.setExportOpen);
  const activeId = useViewer((s) => s.activeId);
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  const setStatus = useViewer((s) => s.setStatus);
  const measures = useViewer((s) =>
    s.activeId ? (s.measures[s.activeId] ?? NO_MEASURES) : NO_MEASURES,
  );

  const [format, setFormat] = useState<Format>("png");
  const [scale, setScale] = useState(1);
  // publication sizing (Quick-Wins #3): integer-scale vs physical mm-width@dpi
  const [sizeMode, setSizeMode] = useState<"scale" | "physical">("scale");
  const [widthMm, setWidthMm] = useState(89); // Nature single-column default
  const [dpi, setDpi] = useState(300);
  const [scaleBar, setScaleBar] = useState(true);
  const [bakeMeasures, setBakeMeasures] = useState(true);
  const [colorbar, setColorbar] = useState(false);
  const [captionText, setCaptionText] = useState("");
  const [metaLine, setMetaLine] = useState(false);
  const [busy, setBusy] = useState(false);

  // live preview state
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [previewErr, setPreviewErr] = useState<string | null>(null);
  const urlRef = useRef<string | null>(null);

  // re-seed every export option from saved prefs each time the dialog opens
  // (Preferences → Export; our pipeline is integer-scale, not DPI).
  // Caption is per-export and intentionally NOT persisted — reset on open.
  useEffect(() => {
    if (open) {
      const p = loadPrefs();
      setFormat(p.exportFormat);
      setScale(Math.min(4, Math.max(1, Math.round(p.exportScale))));
      setSizeMode("scale");
      setScaleBar(p.exportScaleBar);
      setBakeMeasures(p.exportMeasures);
      setColorbar(p.exportColorbar);
      setCaptionText("");
      setMetaLine(false);
    }
  }, [open]);

  const metaLineStr = useMemo(() => {
    if (!meta) return "";
    const parts = [meta.name, `${meta.shape[1]}×${meta.shape[0]} px`];
    if (meta.pixel_size != null)
      parts.push(`${fmtNum(meta.pixel_size)} ${meta.pixel_unit}/px`);
    return parts.join(" · ");
  }, [meta]);

  // the composed caption sent to the backend: user line + optional auto
  // metadata line, newline-separated
  const caption = useMemo(() => {
    const lines: string[] = [];
    if (captionText.trim()) lines.push(captionText.trim());
    if (metaLine && metaLineStr) lines.push(metaLineStr);
    return lines.join("\n");
  }, [captionText, metaLine, metaLineStr]);

  const exportable = !!activeId && !!meta && meta.kind !== "spectrum";

  // debounced live preview — bakes the SAME overlays as the real export
  useEffect(() => {
    if (!open || !exportable) return;
    let cancelled = false;
    setPreviewBusy(true);
    const timer = setTimeout(() => {
      previewActive({
        format,
        scale: 1,
        scaleBar,
        measures: bakeMeasures,
        colorbar,
        caption,
      })
        .then((blob) => {
          if (cancelled) return;
          const url = URL.createObjectURL(blob);
          if (urlRef.current) URL.revokeObjectURL(urlRef.current);
          urlRef.current = url;
          setPreviewUrl(url);
          setPreviewErr(null);
        })
        .catch((e: Error) => {
          if (!cancelled) setPreviewErr(e.message);
        })
        .finally(() => {
          if (!cancelled) setPreviewBusy(false);
        });
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [open, exportable, format, scaleBar, bakeMeasures, colorbar, caption]);

  // drop the object URL when the dialog closes / unmounts (no leaks)
  useEffect(() => {
    if (!open && urlRef.current) {
      URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
      setPreviewUrl(null);
    }
  }, [open]);
  useEffect(
    () => () => {
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    },
    [],
  );

  if (!open) return null;
  if (!exportable || !meta) {
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

  // physical sizing is meaningless for the quantitative tiff16 export
  const physicalAllowed = format !== "tiff16";
  const effPhysical = sizeMode === "physical" && physicalAllowed;

  // output dimensions: integer multiple, or derived from physical width@dpi
  let w: number;
  let h: number;
  if (effPhysical) {
    w = Math.max(1, Math.round((widthMm / 25.4) * dpi));
    h = Math.max(1, Math.round(meta.shape[0] * (w / meta.shape[1])));
  } else {
    w = meta.shape[1] * scale;
    h = meta.shape[0] * scale;
  }
  const bytesPerPx = format === "tiff16" ? 2 : 3;
  const estBytes = w * h * bytesPerPx * SIZE_FACTOR[format];
  const canBar = format !== "tiff16" && meta.pixel_size !== null;
  const canMeasure = format !== "tiff16" && measures.length > 0;
  const canCaption = format !== "tiff16";

  const included: string[] = [];
  if (canBar && scaleBar) included.push("scale bar");
  if (canMeasure && bakeMeasures)
    included.push(`${measures.length} measurement${measures.length === 1 ? "" : "s"}`);
  if (canCaption && colorbar) included.push("colorbar");
  if (canCaption && caption) included.push("caption");
  const summary = included.length ? included.join(", ") : "image only";

  const run = () => {
    setBusy(true);
    exportActive({
      format,
      scale,
      scaleBar,
      measures: bakeMeasures,
      colorbar,
      caption,
      ...(effPhysical ? { widthMm, dpi } : {}),
    })
      .then((filename) => {
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

        <div className="fvd-export-body">
          <div className="fvd-export-left">
            <div className="fvd-export-preview">
              {previewUrl ? (
                <img src={previewUrl} alt="export preview" />
              ) : (
                <span className="fvd-export-ph">
                  {previewErr ? `preview: ${previewErr}` : "rendering…"}
                </span>
              )}
              {previewBusy && previewUrl && (
                <span className="fvd-export-spin">updating…</span>
              )}
            </div>
            <label className="fvd-export-field">
              <span className="k">Caption</span>
              <input
                type="text"
                className="fvd-export-cap"
                placeholder="e.g. Fig 1 · 80 kx · HAADF"
                value={captionText}
                disabled={!canCaption}
                onChange={(e) => setCaptionText(e.target.value)}
              />
            </label>
            <label className={`fvd-check${canCaption ? "" : " disabled"}`}>
              <input
                type="checkbox"
                checked={canCaption && metaLine}
                disabled={!canCaption}
                onChange={(e) => setMetaLine(e.target.checked)}
              />
              Metadata line
              <span className="fvd-export-hint">{metaLineStr}</span>
            </label>
          </div>

          <div className="fvd-export-right">
            <div className="fvd-ws-row">
              <span className="k">Preset</span>
              <div className="fvd-seg">
                {(
                  [
                    ["Draft", "png", 1, true, true, false],
                    ["Slides", "png", 2, true, true, true],
                    ["Journal", "png", 4, true, true, false],
                    ["Data", "tiff16", 1, false, false, false],
                  ] as [string, Format, number, boolean, boolean, boolean][]
                ).map(([name, f, s, bar, meas, cbar]) => (
                  <button
                    key={name}
                    className="fvd-seg-btn"
                    title={`${f} ${s}× — publication-style defaults`}
                    onClick={() => {
                      setFormat(f);
                      setScale(s);
                      setScaleBar(bar);
                      setBakeMeasures(meas);
                      setColorbar(cbar);
                    }}
                  >
                    {name}
                  </button>
                ))}
              </div>
            </div>
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
              <span className="k">Sizing</span>
              <div className="fvd-seg">
                <button
                  className={`fvd-seg-btn${!effPhysical ? " active" : ""}`}
                  onClick={() => setSizeMode("scale")}
                >
                  Scale
                </button>
                <button
                  className={`fvd-seg-btn${effPhysical ? " active" : ""}`}
                  disabled={!physicalAllowed}
                  title={
                    physicalAllowed
                      ? "size to a physical width at a target DPI (journals)"
                      : "TIFF-16 is a data export — integer scale only"
                  }
                  onClick={() => setSizeMode("physical")}
                >
                  Physical
                </button>
              </div>
            </div>

            {effPhysical ? (
              <>
                <div className="fvd-ws-row">
                  <span className="k">Width</span>
                  <div className="fvd-seg">
                    {JOURNAL_WIDTHS.map((j) => (
                      <button
                        key={j.label}
                        className={`fvd-seg-btn${widthMm === j.mm ? " active" : ""}`}
                        title={`${j.label} — ${j.mm} mm`}
                        onClick={() => setWidthMm(j.mm)}
                      >
                        {j.label}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="fvd-ws-row">
                  <span className="k">mm · DPI</span>
                  <input
                    type="number"
                    min={1}
                    max={2000}
                    step={1}
                    value={widthMm}
                    style={{ width: 64 }}
                    onChange={(e) =>
                      setWidthMm(Math.max(1, Number(e.target.value) || 1))
                    }
                  />
                  <div className="fvd-seg">
                    {[150, 300, 600].map((d) => (
                      <button
                        key={d}
                        className={`fvd-seg-btn${dpi === d ? " active" : ""}`}
                        onClick={() => setDpi(d)}
                      >
                        {d}
                      </button>
                    ))}
                  </div>
                </div>
              </>
            ) : (
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
            )}

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
              <label className={`fvd-check${canCaption ? "" : " disabled"}`}>
                <input
                  type="checkbox"
                  checked={canCaption && colorbar}
                  disabled={!canCaption}
                  onChange={(e) => setColorbar(e.target.checked)}
                />
                Colorbar
              </label>
            </div>
          </div>
        </div>

        <div className="fvd-export-info">
          {w} × {h} px
          {effPhysical && ` · ${fmtNum(widthMm)} mm @ ${dpi} dpi`} · ~
          {fmtBytes(estBytes)} · includes: {summary}
          {format === "tiff16" && " · 16-bit grayscale (no overlays)"}
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
