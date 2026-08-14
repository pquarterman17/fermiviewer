// Output-mode controls: BF/ABF/ADF/Custom aperture presets (radii + shape),
// COM/DPC/iDPC (descan center only, +calibration for dpc/idpc — see
// FourDComOutputFields), a shared center block, and the Compute action —
// POST /virtual-detector for the first family, POST /com|/dpc|/idpc for
// the second (PLAN_4DSTEM #9 added the second family to this control,
// which previously only drove the aperture path).
//
// Radii show a secondary calibrated-unit readout (mrad, typically) — and
// accept typed input in it — whenever the dataset's detector axes are
// calibrated (see mradConversion.ts); an uncalibrated dataset (bare .mib,
// no .hdr sidecar) keeps the original px-only UI unchanged.

import type { AxisCalOut } from "../../../lib/api";
import { apertureError, useFourD, type ApertureMode } from "../../../store/fourd";
import { comOutputError, isComOutputMode } from "../../../store/fourdComOutput";
import FourDComOutputFields from "./FourDComOutputFields";
import {
  calibratedToPx,
  detCalibration,
  pxToCalibrated,
  roundForDisplay,
} from "./mradConversion";

const MODES: { id: ApertureMode; label: string; title: string }[] = [
  { id: "bf", label: "BF", title: "Bright field — disk at the direct beam" },
  { id: "abf", label: "ABF", title: "Annular bright field — inside the BF disk" },
  { id: "adf", label: "ADF", title: "Annular dark field — outer scattered annulus" },
  { id: "custom", label: "Custom", title: "Freely edit radii, shape and center" },
  { id: "com", label: "COM", title: "Per-probe center-of-mass shift maps (COMy, COMx)" },
  { id: "dpc", label: "DPC", title: "Differential phase contrast: field magnitude/direction/divergence" },
  { id: "idpc", label: "iDPC", title: "Integrated DPC: Fourier-integrated phase-contrast image" },
];

const COMPUTE_LABELS: Record<"com" | "dpc" | "idpc", string> = {
  com: "Compute COM",
  dpc: "Compute DPC",
  idpc: "Compute iDPC",
};

/** The px readout plus, when calibrated, a paired editable field in the
 *  calibrated unit — least-cluttered way to add a second unit to an
 *  existing slider row without a mode toggle. */
function CalibratedRadiusField({
  px,
  scale,
  units,
  onChangePx,
}: {
  px: number;
  scale: number;
  units: string;
  onChangePx: (px: number) => void;
}) {
  const display = roundForDisplay(pxToCalibrated(px, scale));
  return (
    <>
      <input
        type="number"
        step="any"
        aria-label={`radius in ${units}`}
        style={{ width: 64 }}
        value={Number.isFinite(display) ? display : ""}
        onChange={(e) => {
          const v = Number(e.target.value);
          if (Number.isFinite(v)) onChangePx(calibratedToPx(v, scale));
        }}
      />
      <span className="k">{units}</span>
    </>
  );
}

export default function FourDApertureControls({
  detShape,
  detAxes,
}: {
  detShape: [number, number];
  detAxes?: AxisCalOut[] | null;
}) {
  const aperture = useFourD((s) => s.aperture);
  const setApertureMode = useFourD((s) => s.setApertureMode);
  const setApertureField = useFourD((s) => s.setApertureField);
  const setAutoCenter = useFourD((s) => s.setAutoCenter);
  const computeMap = useFourD((s) => s.computeMap);
  const computeComOutput = useFourD((s) => s.computeComOutput);
  const busyCompute = useFourD((s) => s.busyCompute);
  const selectedId = useFourD((s) => s.selectedId);
  const status = useFourD((s) => s.status);

  const maxR = Math.max(detShape[0], detShape[1]) / 2;
  const isComOutput = isComOutputMode(aperture.mode);
  const error = isComOutput
    ? comOutputError(
        aperture.mode,
        aperture.mradPerPx,
        aperture.highPassCutoff,
        aperture.autoCenter,
        aperture.centerKy,
        aperture.centerKx,
        detShape,
      )
    : apertureError(aperture, detShape);
  const cal = detCalibration(detAxes);

  return (
    <>
      <div className="fvd-ws-row">
        <span className="k">Aperture</span>
        <div className="fvd-seg">
          {MODES.map((m) => (
            <button
              key={m.id}
              className={`fvd-seg-btn${aperture.mode === m.id ? " active" : ""}`}
              title={m.title}
              onClick={() => setApertureMode(m.id)}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>

      {!isComOutput && aperture.mode === "custom" && (
        <div className="fvd-ws-row">
          <span className="k">shape</span>
          <div className="fvd-seg">
            {(["circle", "annulus"] as const).map((shape) => (
              <button
                key={shape}
                className={`fvd-seg-btn${aperture.shape === shape ? " active" : ""}`}
                onClick={() => setApertureField({ shape })}
              >
                {shape}
              </button>
            ))}
          </div>
        </div>
      )}

      {!isComOutput && aperture.shape === "annulus" && (
        <div className="fvd-ws-row">
          <span className="k">inner r</span>
          <input
            type="range"
            min={0}
            max={maxR}
            step={0.5}
            value={aperture.innerR}
            onChange={(e) => setApertureField({ innerR: Number(e.target.value) })}
            style={{ flex: 1 }}
          />
          <span className="k" style={{ width: 40, textAlign: "right" }}>
            {aperture.innerR.toFixed(1)} px
          </span>
          {cal && (
            <CalibratedRadiusField
              px={aperture.innerR}
              scale={cal.scale}
              units={cal.units}
              onChangePx={(innerR) => setApertureField({ innerR })}
            />
          )}
        </div>
      )}

      {!isComOutput && (
        <div className="fvd-ws-row">
          <span className="k">outer r</span>
          <input
            type="range"
            min={0}
            max={maxR}
            step={0.5}
            value={aperture.outerR}
            onChange={(e) => setApertureField({ outerR: Number(e.target.value) })}
            style={{ flex: 1 }}
          />
          <span className="k" style={{ width: 40, textAlign: "right" }}>
            {aperture.outerR.toFixed(1)} px
          </span>
          {cal && (
            <CalibratedRadiusField
              px={aperture.outerR}
              scale={cal.scale}
              units={cal.units}
              onChangePx={(outerR) => setApertureField({ outerR })}
            />
          )}
        </div>
      )}

      {isComOutput && <FourDComOutputFields mode={aperture.mode} cal={cal} />}

      <div className="fvd-ws-row">
        <label className="fvd-check">
          <input
            type="checkbox"
            checked={aperture.autoCenter}
            onChange={(e) => setAutoCenter(e.target.checked)}
          />
          Auto-center from mean pattern
        </label>
      </div>

      {!aperture.autoCenter && (
        <div className="fvd-ws-row">
          <span className="k">center (ky, kx)</span>
          <input
            type="number"
            // a mid-edit NaN (e.g. a lone "-") must show as blank, not the
            // literal string "NaN", in this controlled input — null (not
            // yet edited) still defaults to 0 as before
            value={aperture.centerKy == null ? 0 : Number.isNaN(aperture.centerKy) ? "" : aperture.centerKy}
            style={{ width: 62 }}
            onChange={(e) => setApertureField({ centerKy: Number(e.target.value) })}
          />
          <input
            type="number"
            value={aperture.centerKx == null ? 0 : Number.isNaN(aperture.centerKx) ? "" : aperture.centerKx}
            style={{ width: 62 }}
            onChange={(e) => setApertureField({ centerKx: Number(e.target.value) })}
          />
        </div>
      )}

      <div className="fvd-ws-row">
        <button
          className="fvd-btn primary"
          disabled={!selectedId || busyCompute || !!error}
          title={error ?? undefined}
          onClick={() => void (isComOutput ? computeComOutput() : computeMap())}
        >
          {busyCompute
            ? "Computing…"
            : isComOutputMode(aperture.mode)
              ? COMPUTE_LABELS[aperture.mode]
              : "Compute map"}
        </button>
      </div>
      {error && <div className="fvd-ws-note">{error}</div>}
      {status && <div className="fvd-ws-note">{status}</div>}
    </>
  );
}
