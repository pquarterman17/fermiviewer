// mrad/px calibration + iDPC high-pass cutoff fields — the COM-output
// family's (com/dpc/idpc) counterpart to FourDApertureControls' radii
// rows, rendered only for those three modes (PLAN_4DSTEM #9). "com" needs
// neither field (its descan center is all `/com` takes); "dpc" needs
// mrad/px; "idpc" needs both. Never auto-fills mrad/px from the detector's
// own calibration even when one is available (`cal`) — silently defaulting
// a physical calibration is exactly what calc/fourd/dpc.py's module
// docstring refuses to do server-side, so this control does not do it
// client-side either; `cal` is shown only as a plain-text hint the user
// can copy.

import { useFourD, type ApertureMode } from "../../../store/fourd";
import type { RadiusCalibration } from "./mradConversion";

export default function FourDComOutputFields({
  mode,
  cal,
}: {
  mode: ApertureMode;
  cal: RadiusCalibration | null;
}) {
  const aperture = useFourD((s) => s.aperture);
  const setMradPerPx = useFourD((s) => s.setMradPerPx);
  const setHighPassCutoff = useFourD((s) => s.setHighPassCutoff);

  if (mode === "com") return null;

  return (
    <>
      <div className="fvd-ws-row">
        <span className="k">mrad / px</span>
        <input
          type="number"
          step="any"
          aria-label="detector mrad per pixel"
          style={{ width: 72 }}
          // null (never typed) and a mid-edit NaN (e.g. a lone "-") both
          // show as blank, matching the manual-center fields' idiom below
          // — mrad/px has no sane 0 default to fall back to (0 is itself
          // an invalid calibration), so unlike those fields this one is
          // blank rather than 0 while unset.
          value={
            aperture.mradPerPx == null || Number.isNaN(aperture.mradPerPx)
              ? ""
              : aperture.mradPerPx
          }
          onChange={(e) => {
            const raw = e.target.value;
            setMradPerPx(raw === "" ? null : Number(raw));
          }}
        />
        {cal && cal.units === "mrad" && (
          <span className="k">detector: {cal.scale} mrad/px</span>
        )}
      </div>

      {mode === "idpc" && (
        <div className="fvd-ws-row">
          <span className="k">high-pass cutoff</span>
          <input
            type="number"
            step="any"
            min={0}
            aria-label="high-pass cutoff in cycles per scan pixel"
            style={{ width: 72 }}
            value={aperture.highPassCutoff}
            onChange={(e) => {
              const v = Number(e.target.value);
              if (Number.isFinite(v)) setHighPassCutoff(v);
            }}
          />
          <span className="k">cycles/px</span>
        </div>
      )}
    </>
  );
}
