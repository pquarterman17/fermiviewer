// Aperture controls: BF/ABF/ADF/custom mode presets, radii + center fields,
// auto-center toggle, and the Compute map action (POST /virtual-detector).

import type { ApertureMode } from "../../../store/fourd";
import { useFourD } from "../../../store/fourd";

const MODES: { id: ApertureMode; label: string; title: string }[] = [
  { id: "bf", label: "BF", title: "Bright field — disk at the direct beam" },
  { id: "abf", label: "ABF", title: "Annular bright field — inside the BF disk" },
  { id: "adf", label: "ADF", title: "Annular dark field — outer scattered annulus" },
  { id: "custom", label: "Custom", title: "Freely edit radii, shape and center" },
];

export default function FourDApertureControls({
  detShape,
}: {
  detShape: [number, number];
}) {
  const aperture = useFourD((s) => s.aperture);
  const setApertureMode = useFourD((s) => s.setApertureMode);
  const setApertureField = useFourD((s) => s.setApertureField);
  const setAutoCenter = useFourD((s) => s.setAutoCenter);
  const computeMap = useFourD((s) => s.computeMap);
  const busyCompute = useFourD((s) => s.busyCompute);
  const selectedId = useFourD((s) => s.selectedId);
  const status = useFourD((s) => s.status);

  const maxR = Math.max(detShape[0], detShape[1]) / 2;

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

      {aperture.mode === "custom" && (
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

      {aperture.shape === "annulus" && (
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
            {aperture.innerR.toFixed(1)}
          </span>
        </div>
      )}

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
          {aperture.outerR.toFixed(1)}
        </span>
      </div>

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
            value={aperture.centerKy ?? 0}
            style={{ width: 62 }}
            onChange={(e) => setApertureField({ centerKy: Number(e.target.value) })}
          />
          <input
            type="number"
            value={aperture.centerKx ?? 0}
            style={{ width: 62 }}
            onChange={(e) => setApertureField({ centerKx: Number(e.target.value) })}
          />
        </div>
      )}

      <div className="fvd-ws-row">
        <button
          className="fvd-btn primary"
          disabled={!selectedId || busyCompute}
          onClick={() => void computeMap()}
        >
          {busyCompute ? "Computing…" : "Compute map"}
        </button>
      </div>
      {status && <div className="fvd-ws-note">{status}</div>}
    </>
  );
}
