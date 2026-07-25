import type { ReactNode } from "react";

export type EdsSpectrumSource = "sum" | "live" | "picker";

export default function EdsSpectrumPanel({
  source,
  label,
  busy,
  liveActive,
  logScale,
  expanded,
  onShowSum,
  onToggleLive,
  onShowPicker,
  onToggleLog,
  onToggleExpanded,
  children,
}: {
  source: EdsSpectrumSource;
  label: string;
  busy: boolean;
  liveActive: boolean;
  logScale: boolean;
  expanded: boolean;
  onShowSum: () => void;
  onToggleLive: () => void;
  onShowPicker: () => void;
  onToggleLog: () => void;
  onToggleExpanded: () => void;
  children: ReactNode;
}) {
  return (
    <section className="fvd-eds-spectrum-panel" aria-label="EDS spectrum viewer">
      <header className="fvd-eds-spectrum-header">
        <div>
          <strong>Spectrum</strong>
          <span className="fvd-eds-source-chip" aria-live="polite">
            {busy ? "Loading…" : label}
          </span>
        </div>
        <div className="fvd-eds-spectrum-actions">
          <button
            type="button"
            className={`fvd-btn${logScale ? " active" : ""}`}
            aria-pressed={logScale}
            onClick={onToggleLog}
          >
            Log counts
          </button>
          <button
            type="button"
            className="fvd-btn"
            aria-pressed={expanded}
            onClick={onToggleExpanded}
          >
            {expanded ? "Compact" : "Expand"}
          </button>
        </div>
      </header>

      <div className="fvd-eds-source-bar" role="group" aria-label="Spectrum source">
        <span className="k">Source</span>
        <button
          type="button"
          className={`fvd-seg-btn${source === "sum" ? " active" : ""}`}
          aria-pressed={source === "sum"}
          onClick={onShowSum}
        >
          Whole cube
        </button>
        <button
          type="button"
          className={`fvd-seg-btn${source === "live" ? " active" : ""}`}
          aria-pressed={liveActive}
          onClick={onToggleLive}
        >
          Live stage pixel
        </button>
        <button
          type="button"
          className={`fvd-seg-btn${source === "picker" ? " active" : ""}`}
          aria-pressed={source === "picker"}
          onClick={onShowPicker}
        >
          Preview pixel / ROI
        </button>
      </div>

      {children}
      <div className="fvd-eds-spectrum-axis-label">
        Energy ({logScale ? "keV · log₁₀(counts + 1)" : "keV · counts"})
      </div>
    </section>
  );
}
