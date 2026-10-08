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

import { useState } from "react";

import type { EdsMapBackground } from "../../lib/eds/background";
import WindowPresetBar from "../spectrum/WindowPresetBar";
import type { WindowPreset } from "../../lib/spectrum/windowPresets";

/** Smallest window the typed bounds may leave (keV) — one 5 eV step. */
const MIN_WIDTH_KEV = 0.005;

/** A typed window [lo, hi] made valid: finite, inside `range` when known,
 *  and lo < hi. Returns null when the text is not a number at all. */
export function clampWindow(
  lo: number,
  hi: number,
  range: readonly [number, number] | null,
): [number, number] | null {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return null;
  let a = Math.min(lo, hi);
  let b = Math.max(lo, hi);
  if (range) {
    const [rLo, rHi] = range[0] <= range[1] ? range : [range[1], range[0]];
    a = Math.min(Math.max(a, rLo), rHi - MIN_WIDTH_KEV);
    b = Math.max(Math.min(b, rHi), a + MIN_WIDTH_KEV);
  } else if (b - a < MIN_WIDTH_KEV) {
    b = a + MIN_WIDTH_KEV;
  }
  return [a, b];
}

/** A number field that keeps its own draft text while focused and commits
 *  on blur or Enter. Controlled `value={x.toFixed(3)}` re-formatted the
 *  field on every keystroke (and the symmetric lock moved the partner), so
 *  nothing could be typed into it. Escape reverts. */
function DraftNumber({
  value,
  onCommit,
  title,
  label,
}: {
  value: number;
  onCommit: (v: number) => void;
  title: string;
  label: string;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const commit = () => {
    if (draft === null) return;
    setDraft(null);
    const v = Number(draft.trim());
    if (draft.trim() !== "" && Number.isFinite(v)) onCommit(v);
  };
  return (
    <input
      type="number"
      step={0.005}
      aria-label={label}
      value={draft ?? value.toFixed(3)}
      style={{ width: 78 }}
      onFocus={(e) => setDraft(e.target.value)}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit();
        if (e.key === "Escape") setDraft(null);
      }}
      title={title}
    />
  );
}

export default function EdsWindowControls({
  eLo,
  eHi,
  range,
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
  /** The spectrum's energy extent (keV); typed bounds are clamped into it. */
  range: readonly [number, number] | null;
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
  const commitWindow = (lo: number, hi: number) => {
    const w = clampWindow(lo, hi, range);
    if (w) onWindow(w[0], w[1]);
  };
  return (
    <>
      <div className="fvd-ws-row">
        <span className="k">Window (keV)</span>
        <DraftNumber
          label="Window low (keV)"
          value={eLo}
          onCommit={(v) => commitWindow(v, eHi)}
          title="Energy window low (keV) — applied on Enter or when leaving the field"
        />
        <span style={{ padding: "0 4px" }}>–</span>
        <DraftNumber
          label="Window high (keV)"
          value={eHi}
          onCommit={(v) => commitWindow(eLo, v)}
          title="Energy window high (keV) — applied on Enter or when leaving the field"
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
