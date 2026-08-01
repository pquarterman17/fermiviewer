// LayersWorkshop parameter form: axis, modality, sensitivity/#layers,
// waviness, de-curtain, foil-thickness rows and the Analyze button. Split
// out of LayersWorkshop.tsx (repo-health #33). Moved verbatim — purely
// presentational, all state lives in the parent workshop.

interface LayersControlsProps {
  axis: "auto" | "y" | "x";
  onAxisChange: (axis: "auto" | "y" | "x") => void;
  modality: "haadf" | "eels" | "bf" | "df";
  onModalityChange: (modality: "haadf" | "eels" | "bf" | "df") => void;
  sensitivity: string;
  onSensitivityChange: (value: string) => void;
  nLayers: string;
  onNLayersChange: (value: string) => void;
  busy: boolean;
  activeId: string | null;
  onRun: () => void;
  waviness: boolean;
  onWavinessChange: (value: boolean) => void;
  decurtain: boolean;
  onDecurtainChange: (value: boolean) => void;
  foilT: string;
  onFoilTChange: (value: string) => void;
}

export function LayersControls({
  axis,
  onAxisChange,
  modality,
  onModalityChange,
  sensitivity,
  onSensitivityChange,
  nLayers,
  onNLayersChange,
  busy,
  activeId,
  onRun,
  waviness,
  onWavinessChange,
  decurtain,
  onDecurtainChange,
  foilT,
  onFoilTChange,
}: LayersControlsProps) {
  return (
    <>
      <div className="fvd-ws-row">
        <span className="k">Axis</span>
        <div className="fvd-seg">
          {(["auto", "y", "x"] as const).map((a) => (
            <button
              key={a}
              className={`fvd-seg-btn${axis === a ? " active" : ""}`}
              title={a === "auto" ? "auto-detect growth axis" : `layers stack along ${a}`}
              onClick={() => onAxisChange(a)}
            >
              {a}
            </button>
          ))}
        </div>
      </div>
      <div className="fvd-ws-row">
        <span className="k">Modality</span>
        <div className="fvd-seg">
          {(["haadf", "eels", "bf", "df"] as const).map((m) => (
            <button
              key={m}
              className={`fvd-seg-btn${modality === m ? " active" : ""}`}
              title={
                m === "bf" || m === "df"
                  ? "scale-space interface detection (rejects thickness fringes)"
                  : `${m} (intensity-step detection)`
              }
              onClick={() => onModalityChange(m)}
            >
              {m.toUpperCase()}
            </button>
          ))}
        </div>
      </div>
      <div className="fvd-ws-row">
        <span className="k">Sensitivity</span>
        <input
          value={sensitivity}
          style={{ width: 48 }}
          title="Interface peak threshold (fraction of max gradient) — lower finds more"
          onChange={(e) => onSensitivityChange(e.target.value)}
        />
        <span className="k"># layers</span>
        <input
          value={nLayers}
          placeholder="auto"
          style={{ width: 44 }}
          title="Optional hint: keep only the (n−1) strongest interfaces"
          onChange={(e) => onNLayersChange(e.target.value)}
        />
        <button
          className="fvd-btn"
          title="Detect layers & interface sharpness (σ_erf)"
          onClick={onRun}
          disabled={busy || !activeId}
        >
          {busy ? "Analyzing…" : "Analyze"}
        </button>
      </div>
      <div className="fvd-ws-row">
        <label className="k" style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <input
            type="checkbox"
            checked={waviness}
            onChange={(e) => onWavinessChange(e.target.checked)}
          />
          waviness (σ_w)
        </label>
        <span className="k" style={{ fontSize: 10, opacity: 0.7 }}>
          per-column trace → detrended robust roughness ±CI, spectrum, conformality
        </span>
      </div>
      <div className="fvd-ws-row">
        <label className="k" style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <input
            type="checkbox"
            checked={decurtain}
            onChange={(e) => onDecurtainChange(e.target.checked)}
          />
          de-curtain (FIB)
        </label>
        <span className="k" style={{ fontSize: 10, opacity: 0.7 }}>
          robust median collapse + FFT notch — suppresses FIB milling streaks
        </span>
      </div>
      <div className="fvd-ws-row">
        <span className="k">≈ foil t</span>
        <input
          value={foilT}
          placeholder="optional"
          style={{ width: 56 }}
          title="Approximate TEM foil thickness (same units as the calibration). Roughness at lateral wavelengths shorter than the foil is projection-smeared — the PSD marks that region and σ_w reads as a lower bound."
          onChange={(e) => onFoilTChange(e.target.value)}
        />
        <span className="k" style={{ fontSize: 10, opacity: 0.7 }}>
          marks projection-limited wavelengths in the roughness spectrum
        </span>
      </div>
    </>
  );
}
