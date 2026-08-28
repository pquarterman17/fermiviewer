import type { Dispatch, RefObject, SetStateAction } from "react";

import type {
  AnalysisRoi,
  CalibrationResult,
  PhaseCandidate,
  PhaseInfo,
  SimulateResult,
} from "../../lib/api";

type RoiMode = "none" | "rect" | "circle";

interface IndexPanelProps {
  minRadius: string;
  setMinRadius: Dispatch<SetStateAction<string>>;
  threshold: string;
  setThreshold: Dispatch<SetStateAction<string>>;
  pixelSize: string;
  setPixelSize: Dispatch<SetStateAction<string>>;
  cameraLen: string;
  setCameraLen: Dispatch<SetStateAction<string>>;
  accKv: string;
  setAccKv: Dispatch<SetStateAction<string>>;
  busy: boolean;
  detect: () => void;
  rings: boolean;
  setRings: Dispatch<SetStateAction<boolean>>;
  labels: boolean;
  setLabels: Dispatch<SetStateAction<boolean>>;
  clickMode: boolean;
  setClickMode: Dispatch<SetStateAction<boolean>>;
  spotsLength: number;
  typedD: string;
  setTypedD: Dispatch<SetStateAction<string>>;
  typedRingR: number | null;
  index: () => void;
  candidates: PhaseCandidate[];
  selectedCandIdx: number;
  setSelectedCandIdx: Dispatch<SetStateAction<number>>;
  downloadReport: (fmt: "csv" | "json") => void;
  roiMode: RoiMode;
  setRoiMode: Dispatch<SetStateAction<RoiMode>>;
  committedRoi: AnalysisRoi | null;
  clearRoi: () => void;
  saveResult: boolean;
  setSaveResult: Dispatch<SetStateAction<boolean>>;
}

export function DiffractionIndexPanel(props: IndexPanelProps) {
  const {
    minRadius, setMinRadius, threshold, setThreshold, pixelSize, setPixelSize,
    cameraLen, setCameraLen, accKv, setAccKv, busy, detect, rings, setRings,
    labels, setLabels, clickMode, setClickMode, spotsLength, typedD, setTypedD,
    typedRingR, index, candidates, selectedCandIdx, setSelectedCandIdx,
    downloadReport, roiMode, setRoiMode, committedRoi, clearRoi,
    saveResult, setSaveResult,
  } = props;
  const selected = candidates[selectedCandIdx];
  return <>
    <div className="fvd-ws-row">
      <span className="k">min r</span><input value={minRadius} style={{ width: 44 }} onChange={(e) => setMinRadius(e.target.value)} />
      <span className="k">thresh</span><input value={threshold} style={{ width: 52 }} onChange={(e) => setThreshold(e.target.value)} />
      <button className="fvd-btn" title="Detect diffraction spots (uses min r + threshold, and ROI if set)" onClick={detect} disabled={busy}>Detect</button>
      <label className="fvd-check"><input type="checkbox" checked={rings} onChange={(e) => setRings(e.target.checked)} />Rings</label>
      <label className="fvd-check" title="label each matched spot with its (hkl) + measured d on the pattern"><input type="checkbox" checked={labels} onChange={(e) => setLabels(e.target.checked)} />Labels</label>
    </div>
    <div className="fvd-ws-row">
      <button className={`fvd-btn${clickMode ? " active" : ""}`} onClick={() => setClickMode((v) => !v)} title="Click spots manually on the pattern preview (A7)">{clickMode ? "Done Clicking" : "Click Spots"}</button>
      {clickMode && <span className="fvd-ws-hint">Click to add · click existing to remove</span>}
      {spotsLength > 0 && !clickMode && <span className="fvd-ws-hint">{spotsLength} spots</span>}
    </div>
    <div className="fvd-ws-row">
      <span className="k">d (Å)</span><input value={typedD} style={{ width: 64 }} placeholder="e.g. 2.338" title="Type a d-spacing (Å) to preview the matching ring on the pattern" onChange={(e) => setTypedD(e.target.value)} />
      {typedRingR !== null ? <span className="fvd-ws-hint">{typedRingR.toFixed(1)} px</span> : typedD ? <span className="fvd-ws-hint" style={{ color: "var(--error, #f87171)" }}>out of range</span> : null}
    </div>
    <div className="fvd-ws-row">
      <span className="k">px (mm)</span><input value={pixelSize} style={{ width: 52 }} onChange={(e) => setPixelSize(e.target.value)} />
      <span className="k">L (mm)</span><input value={cameraLen} placeholder="auto" style={{ width: 52 }} onChange={(e) => setCameraLen(e.target.value)} />
      <span className="k">kV</span><input value={accKv} style={{ width: 44 }} onChange={(e) => setAccKv(e.target.value)} />
      <button className="fvd-btn" title="Index the detected spots against candidate phases" onClick={index} disabled={busy || spotsLength === 0}>Index</button>
      <label className="fvd-check" title="Keep this indexing run and its settings in Results & Methods"><input type="checkbox" checked={saveResult} onChange={(e) => setSaveResult(e.target.checked)} />Save result</label>
    </div>
    {candidates.length > 0 && <>
      <table className="fvd-ws-table"><thead><tr><th></th><th>Phase</th><th>Zone</th><th>Matched</th><th>Score</th></tr></thead><tbody>
        {candidates.map((c, i) => <tr key={`${c.phase}-${c.zone_axis.join("")}`} style={{ cursor: "pointer", background: i === selectedCandIdx ? "rgba(34,197,94,0.12)" : undefined }} onClick={() => setSelectedCandIdx(i)}><td>{i === selectedCandIdx ? "●" : ""}</td><td title={c.formula}>{c.phase}</td><td>[{c.zone_axis.join(" ")}]</td><td>{c.n_matched}</td><td>{c.score.toFixed(3)}</td></tr>)}
      </tbody></table>
      <div className="fvd-ws-row"><span className="k">report</span><button className="fvd-btn" disabled={(selected?.n_matched ?? 0) === 0} title="Download the measured-vs-reference indexing table (CSV)" onClick={() => downloadReport("csv")}>CSV</button><button className="fvd-btn" disabled={(selected?.n_matched ?? 0) === 0} title="Download the indexing report with provenance (JSON)" onClick={() => downloadReport("json")}>JSON</button></div>
      <div className="fvd-ws-note" style={{ fontSize: 10 }}>Click a row to select · Rings overlays d-spacings · Labels tags each spot with (hkl) + d</div>
    </>}
    <div className="fvd-ws-section" style={{ marginTop: 6 }}><span>Analysis ROI</span></div>
    <div className="fvd-ws-row">
      <button className={`fvd-btn${roiMode === "rect" ? " active" : ""}`} title="Draw a rectangular ROI — detect/index will use only this region" onClick={() => setRoiMode((m) => m === "rect" ? "none" : "rect")}>Rect</button>
      <button className={`fvd-btn${roiMode === "circle" ? " active" : ""}`} title="Draw a circular ROI — click centre then edge" onClick={() => setRoiMode((m) => m === "circle" ? "none" : "circle")}>Circle</button>
      <button className="fvd-btn" title="Clear the Analysis ROI — detect/index revert to full image" disabled={!committedRoi} onClick={clearRoi}>Clear ROI</button>
      {committedRoi && <span className="fvd-ws-hint">{committedRoi.kind === "rect" ? `${committedRoi.c1 - committedRoi.c0}×${committedRoi.r1 - committedRoi.r0} px` : `r=${committedRoi.radius} px`}</span>}
    </div>
    {roiMode !== "none" && <div className="fvd-ws-note">{roiMode === "rect" ? "Drag on the pattern to draw a rect ROI" : "Click centre then drag to edge for circle ROI"}</div>}
  </>;
}

interface CalibrationPanelProps {
  calKnownD: string; setCalKnownD: Dispatch<SetStateAction<string>>; busy: boolean;
  activeId: string | null; calibrate: () => void; calib: CalibrationResult | null;
}
export function DiffractionCalibrationPanel({ calKnownD, setCalKnownD, busy, activeId, calibrate, calib }: CalibrationPanelProps) {
  return <>
    <div className="fvd-ws-section"><span>Calibrate rings</span></div>
    <div className="fvd-ws-row"><span className="k">known d (Å)</span><input value={calKnownD} style={{ width: 60 }} placeholder="auto" title="known standard ring d-spacing; blank → use the selected phase's 111" onChange={(e) => setCalKnownD(e.target.value)} /><button className="fvd-btn" title="Fit ring ellipse to calibrate distortion & camera constant" onClick={calibrate} disabled={busy || !activeId}>Fit ellipse</button></div>
    {calib && <div className="fvd-ws-note">ecc {calib.ellipse.eccentricity.toFixed(3)} · a/b {calib.ellipse.a.toFixed(1)}/{calib.ellipse.b.toFixed(1)} px · θ {calib.ellipse.theta_deg.toFixed(1)}° · RMS {calib.rms_residual_px.toFixed(2)} px{calib.camera_constant_px_ang != null && <> · C {calib.camera_constant_px_ang.toFixed(1)} px·Å</>}</div>}
  </>;
}

interface SimulationPanelProps {
  phases: PhaseInfo[]; simPhase: string; setSimPhase: Dispatch<SetStateAction<string>>;
  cifInputRef: RefObject<HTMLInputElement | null>; onCifFile: (file: File) => void;
  deletePhase: () => void; scatModel: "fe" | "z"; setScatModel: Dispatch<SetStateAction<"fe" | "z">>;
  simZa: string; setSimZa: Dispatch<SetStateAction<string>>; simulate: () => void; busy: boolean;
  simResult: SimulateResult | null;
}
export function DiffractionSimulationPanel(props: SimulationPanelProps) {
  const { phases, simPhase, setSimPhase, cifInputRef, onCifFile, deletePhase, scatModel, setScatModel, simZa, setSimZa, simulate, busy, simResult } = props;
  return <>
    <div className="fvd-ws-section"><span>Simulate</span></div>
    <div className="fvd-ws-row"><span className="k">Phase</span><select value={simPhase} style={{ flex: 1 }} onChange={(e) => setSimPhase(e.target.value)}>{phases.map((p) => <option key={p.name} value={p.name} title={p.formula}>{p.custom ? "★ " : ""}{p.name}</option>)}</select><button className="fvd-btn" title="Import a phase from a .cif file" onClick={() => cifInputRef.current?.click()}>+ CIF</button>{phases.find((x) => x.name === simPhase)?.custom && <button className="fvd-btn" title="delete this custom phase" onClick={deletePhase}>×</button>}<input ref={cifInputRef} type="file" accept=".cif" style={{ display: "none" }} onChange={(e) => { const f = e.target.files?.[0]; if (f) onCifFile(f); e.target.value = ""; }} /></div>
    <div className="fvd-ws-row"><span className="k">intensities</span><select value={scatModel} style={{ flex: 1 }} title="electron scattering factors (Doyle–Turner) vs the atomic-number proxy" onChange={(e) => setScatModel(e.target.value as "fe" | "z")}><option value="fe">Scattering factors (Doyle–Turner)</option><option value="z">Z proxy (legacy)</option></select></div>
    <div className="fvd-ws-row"><span className="k">Zone axis</span><input value={simZa} style={{ width: 80 }} placeholder="0 0 1" onChange={(e) => setSimZa(e.target.value)} /><button className="fvd-btn" title="Simulate the kinematic diffraction pattern for the phase + zone axis" onClick={simulate} disabled={busy || !simPhase}>Simulate</button></div>
    {simResult && <><div className="fvd-ws-note">{simResult.phase} ({simResult.formula}) [{simResult.zone_axis.join(" ")}] · {simResult.spots.length} spots · λ {simResult.lam_angstrom.toFixed(4)} Å{simResult.image && " · pattern added to library"}</div><table className="fvd-ws-table"><thead><tr><th>hkl</th><th>d (Å)</th><th>I</th></tr></thead><tbody>{simResult.spots.slice(0, 12).map((s, i) => <tr key={i}><td>[{s.hkl.join(" ")}]</td><td>{s.d_spacing != null ? s.d_spacing.toFixed(3) : "—"}</td><td>{s.intensity.toFixed(3)}</td></tr>)}</tbody></table></>}
  </>;
}
