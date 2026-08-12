// Window WIDTH controls, shared by both Explore tabs (plan items #5 and #6).
//
// Presentational only: every number comes from lib/spectrum/windowPresets, so
// what "standard" means is decided once, in the module the tests pin, not
// twice in two workspaces. The button tooltips state the width the press will
// produce — a preset whose effect you have to press to discover is a guess,
// not a preset.
//
// The lock is offered only where it is a real choice. An EDS window is
// CENTRED on its line, so "follow the line" and "sit wherever it was dragged"
// are two defensible behaviours and the user picks. An EELS window STARTS at
// its onset by definition — the presets extend it upward and re-place the
// pre-edge background beneath it, which is onset-following unconditionally.
// A toggle there would only offer to make the window wrong.

import type { Modality } from "../../lib/spectrum/species";
import {
  activePreset,
  presetWidth,
  WINDOW_PRESETS,
  type WindowPreset,
} from "../../lib/spectrum/windowPresets";

/** Width in the modality's own unit, at a precision that unit deserves:
 *  keV windows are tens of eV wide, eV windows are tens of eV wide. */
export function formatWindowWidth(modality: Modality, width: number): string {
  return modality === "eds"
    ? `${(width * 1000).toFixed(0)} eV`
    : `${Number(width.toPrecision(3))} eV`;
}

export default function WindowPresetBar({
  modality,
  anchorEnergy,
  width,
  onPreset,
  onFit,
  fitDisabled,
  fitTitle,
  locked,
  onLocked,
  lockTitle,
}: {
  modality: Modality;
  /** The line (EDS, keV) or onset (EELS, eV) the presets are measured at.
   *  EDS preset widths scale with the detector resolution here, so this is a
   *  physical input, not just a position. */
  anchorEnergy: number;
  /** Current signal-window width, for showing which preset is in effect. */
  width: number;
  onPreset: (preset: WindowPreset) => void;
  /** Omit to hide the Fit button (EELS has no peak to fit — see the header). */
  onFit?: () => void;
  fitDisabled?: boolean;
  fitTitle?: string;
  /** Omit either to hide the lock (see the header for when it is offered). */
  locked?: boolean;
  onLocked?: (locked: boolean) => void;
  lockTitle?: string;
}) {
  const current = activePreset(modality, anchorEnergy, width);
  const showLock = locked != null && onLocked != null;

  return (
    <div className="fvd-ws-row">
      <span className="k">Width</span>
      <div className="fvd-seg">
        {WINDOW_PRESETS.map((preset) => (
          <button
            key={preset}
            type="button"
            className={`fvd-seg-btn${current === preset ? " active" : ""}`}
            aria-pressed={current === preset}
            title={`${preset} — ${formatWindowWidth(
              modality,
              presetWidth(modality, anchorEnergy, preset),
            )}${
              modality === "eds"
                ? " (detector resolution at this line)"
                : " past the edge onset"
            }`}
            onClick={() => onPreset(preset)}
          >
            {preset}
          </button>
        ))}
      </div>
      {onFit && (
        <button
          type="button"
          className="fvd-btn"
          disabled={fitDisabled}
          title={
            fitTitle ??
            "Measure this peak's width in the displayed spectrum and fit the window to it"
          }
          onClick={onFit}
        >
          Fit width
        </button>
      )}
      {showLock && (
        <label className="fvd-check" title={lockTitle}>
          <input
            type="checkbox"
            checked={locked}
            onChange={(e) => onLocked(e.target.checked)}
          />
          Lock to line
        </label>
      )}
    </div>
  );
}
