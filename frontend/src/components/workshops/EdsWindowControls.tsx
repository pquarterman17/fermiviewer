// The EDS energy-window controls: typed bounds, width presets / fit / lock,
// and the background model. Extracted from EdsSpectrumImage (473/500 lines)
// when items #5 and #6 added the preset bar — the ratchet forcing a module
// rather than a bulge, and these rows are one coherent thing anyway: every
// control here changes what the integration window covers or what is
// subtracted from underneath it.
//
// Presentational: it owns no window state. EdsSpectrumImage keeps that,
// because the same window drives the plot, the live readout and the element
// map, and a second copy of it here is exactly the drift these plans keep
// paying for.

import type { EdsMapBackground } from "../../lib/eds/background";
import WindowPresetBar from "../spectrum/WindowPresetBar";
import type { WindowPreset } from "../../lib/spectrum/windowPresets";

export default function EdsWindowControls({
  eLo,
  eHi,
  onWindow,
  onZoomToWindow,
  anchorKev,
  onPreset,
  onFit,
  fitDisabled,
  lineKev,
  locked,
  onLocked,
  bgMode,
  onBgMode,
  e0Kev,
  onE0Kev,
  showPeaks,
  onShowPeaks,
}: {
  eLo: number;
  eHi: number;
  onWindow: (lo: number, hi: number) => void;
  onZoomToWindow: () => void;
  /** Where the presets measure the detector resolution — the locked line, or
   *  the window's own centre when the window is not bound to one. */
  anchorKev: number;
  onPreset: (preset: WindowPreset) => void;
  onFit: () => void;
  fitDisabled: boolean;
  /** The selected element's line, or null when the window is custom. */
  lineKev: number | null;
  locked: boolean;
  onLocked: (locked: boolean) => void;
  bgMode: EdsMapBackground;
  onBgMode: (mode: EdsMapBackground) => void;
  e0Kev: number;
  onE0Kev: (kev: number) => void;
  showPeaks: boolean;
  onShowPeaks: (on: boolean) => void;
}) {
  return (
    <>
      <div className="fvd-ws-row">
        <span className="k">Window (keV)</span>
        <input
          type="number"
          step={0.005}
          value={eLo.toFixed(3)}
          style={{ width: 78 }}
          onChange={(e) => onWindow(Number(e.target.value), eHi)}
          title="Energy window low (keV) — the live net above updates as you type"
        />
        <span style={{ padding: "0 4px" }}>–</span>
        <input
          type="number"
          step={0.005}
          value={eHi.toFixed(3)}
          style={{ width: 78 }}
          onChange={(e) => onWindow(eLo, Number(e.target.value))}
          title="Energy window high (keV) — the live net above updates as you type"
        />
        <span className="k">{((eHi - eLo) * 1000).toFixed(0)} eV wide</span>
        <button
          className="fvd-btn"
          title="Zoom the spectrum to the current energy window"
          onClick={onZoomToWindow}
        >
          Zoom to window
        </button>
      </div>

      <WindowPresetBar
        modality="eds"
        anchorEnergy={anchorKev}
        width={eHi - eLo}
        onPreset={onPreset}
        onFit={onFit}
        fitDisabled={fitDisabled}
        locked={lineKev != null ? locked : undefined}
        onLocked={lineKev != null ? onLocked : undefined}
        lockTitle={
          lineKev != null
            ? `Keep the window centred on ${lineKev.toFixed(3)} keV — resizing ` +
              "then grows it symmetrically about the line instead of letting it drift off"
            : undefined
        }
      />

      <div className="fvd-ws-row">
        <span className="k">Background</span>
        <div className="fvd-seg">
          {(["linear", "none", "bremsstrahlung"] as const).map((m) => (
            <button
              key={m}
              className={`fvd-seg-btn${bgMode === m ? " active" : ""}`}
              title={
                m === "bremsstrahlung"
                  ? "Physical Kramers continuum (per-pixel amplitude fit)"
                  : `${m} background`
              }
              onClick={() => onBgMode(m)}
            >
              {m === "bremsstrahlung" ? "brems" : m}
            </button>
          ))}
        </div>
        {bgMode === "bremsstrahlung" && (
          <>
            <span className="k">E₀ (keV)</span>
            <input
              type="number"
              value={e0Kev}
              style={{ width: 56 }}
              title="Beam energy — Duane–Hunt continuum cutoff"
              onChange={(e) => onE0Kev(Number(e.target.value) || 0)}
            />
          </>
        )}
        <label
          className="k"
          style={{
            marginLeft: "auto",
            display: "flex",
            alignItems: "center",
            gap: 4,
          }}
          title="Label characteristic X-ray peaks on the spectrum (Si Kα, Fe Kα…)"
        >
          <input
            type="checkbox"
            checked={showPeaks}
            onChange={(e) => onShowPeaks(e.target.checked)}
          />
          Label peaks
        </label>
      </div>
    </>
  );
}
