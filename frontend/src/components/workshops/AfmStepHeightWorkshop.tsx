import { useEffect, useRef, useState } from "react";

import { useAnalysisRoi } from "../../hooks/useAnalysisRoi";
import { afmStepHeight, type StepHeightResult } from "../../lib/api";
import { isSpmHeightImage } from "../../lib/spm";
import {
  downloadCsv, downloadJson, exportBaseName, tableToCsv, type Cell,
} from "../../lib/resultsExport";
import { useViewer } from "../../store/viewer";
import AnalysisRegionSelect from "./AnalysisRegionSelect";
import AfmStepEvidence from "./AfmStepEvidence";

const NO_SHAPE: number[] = [];

export function stepHeightRows(result: StepHeightResult): Cell[][] {
  return [
    ["Step height", result.height, result.unit],
    ["Signed step height", result.signed_height, result.unit],
    ["Fit RMS", result.fit_rms, result.unit],
    ["Lower terrace RMS residual", result.lower_std, result.unit],
    ["Upper terrace RMS residual", result.upper_std, result.unit],
    ["Lower terrace pixels", result.n_lower, "px"],
    ["Upper terrace pixels", result.n_upper, "px"],
    ["Upper terrace fraction", result.upper_fraction * 100, "%"],
  ];
}

function format(value: number, unit: string): string {
  const text = Math.abs(value) >= 1e4 || (value !== 0 && Math.abs(value) < 1e-3)
    ? value.toExponential(3) : value.toPrecision(4);
  return unit ? `${text} ${unit}` : text;
}

export default function AfmStepHeightWorkshop() {
  const activeId = useViewer((s) => s.activeId);
  const meta = useViewer((s) => (s.activeId ? (s.images[s.activeId] ?? null) : null));
  const setStatus = useViewer((s) => s.setStatus);
  const region = useAnalysisRoi(activeId, meta?.shape ?? NO_SHAPE);
  const [edge, setEdge] = useState(2);
  const [result, setResult] = useState<StepHeightResult | null>(null);
  const [resultKey, setResultKey] = useState("");
  const [resultRegion, setResultRegion] = useState("");
  const [resultEdge, setResultEdge] = useState(2);
  const [busy, setBusy] = useState(false);
  const [manual, setManual] = useState(false);
  const [splitAxis, setSplitAxis] = useState<"x" | "y">("x");
  const [splitPercent, setSplitPercent] = useState(50);
  const [wholeConfirmed, setWholeConfirmed] = useState(false);
  const request = useRef(0);
  const controlKey = JSON.stringify([region.choice, region.roi, edge, manual, splitAxis, splitPercent]);
  const stale = result !== null && resultKey !== controlKey;

  useEffect(() => {
    request.current += 1;
    setResult(null);
    setBusy(false);
    setWholeConfirmed(false);
  }, [activeId]);
  useEffect(() => { setWholeConfirmed(false); }, [region.choice]);
  useEffect(() => () => { request.current += 1; }, []);

  const run = () => {
    if (!activeId) return;
    const token = ++request.current;
    const runRegion = region.label;
    setBusy(true);
    setStatus("measuring step height…");
    const split = manual ? { axis: splitAxis, fraction: splitPercent / 100 } : undefined;
    (split ? afmStepHeight(activeId, region.roi, edge, split) : afmStepHeight(activeId, region.roi, edge))
      .then((next) => {
        if (token !== request.current) return;
        setResult(next);
        setResultKey(controlKey);
        setResultRegion(runRegion);
        setResultEdge(edge);
        setStatus(`step height ${format(next.height, next.unit)}`);
      })
      .catch((error: Error) => {
        if (token === request.current) setStatus(`step height: ${error.message}`);
      })
      .finally(() => {
        if (token === request.current) setBusy(false);
      });
  };

  const exportResult = (kind: "csv" | "json") => {
    if (!result || stale) return;
    const columns = ["metric", "value", "unit"];
    const provenance = {
      analysis: "AFM step height",
      imageName: meta?.name,
      params: { region: resultRegion, roi: result.roi, edgeExclusionPx: resultEdge },
    };
    const base = `${exportBaseName(meta?.name)}_step_height`;
    if (kind === "csv") downloadCsv(`${base}.csv`, tableToCsv(columns, stepHeightRows(result), provenance));
    else downloadJson(`${base}.json`, `${JSON.stringify({ ...provenance, result }, null, 2)}\n`);
  };

  if (!meta || meta.kind !== "image" || !isSpmHeightImage(meta)) {
    return <div className="fvd-ws-empty">Select an AFM height map.</div>;
  }

  return (
    <div className="fvd-ws">
      <div className="fvd-ws-note">
        Choose or draw a region that crosses one step and includes both flat terraces.
      </div>
      <AnalysisRegionSelect
        choice={region.choice} imageId={activeId} roi={region.roi}
        options={region.options} disabled={busy} onChange={region.setChoice}
      />
      {region.choice === "whole" && <label className="fvd-ws-check"><input type="checkbox" checked={wholeConfirmed} onChange={(event) => setWholeConfirmed(event.target.checked)} /> Use the whole image deliberately</label>}
      <div className="fvd-ws-row">
        <label className="fvd-ws-check"><input type="checkbox" checked={manual} disabled={busy} onChange={(event) => setManual(event.target.checked)} /> Correct terrace split manually</label>
        {manual && <><label className="k" htmlFor="afm-step-axis">Direction</label><select id="afm-step-axis" value={splitAxis} disabled={busy} onChange={(event) => setSplitAxis(event.target.value as "x" | "y")}><option value="x">Left → right</option><option value="y">Top → bottom</option></select><label className="k" htmlFor="afm-step-split">Split</label><input id="afm-step-split" type="range" min={5} max={95} value={splitPercent} disabled={busy} onChange={(event) => setSplitPercent(Number(event.target.value))} /><span className="v">{splitPercent}%</span></>}
      </div>
      <div className="fvd-ws-row">
        <label className="k" htmlFor="afm-step-edge">Ignore step edge</label>
        <input
          id="afm-step-edge" type="number" min={0} max={20} step={1}
          value={edge} disabled={busy}
          onChange={(event) => {
            const value = Number(event.target.value);
            if (Number.isFinite(value)) setEdge(Math.max(0, Math.min(20, Math.round(value))));
          }}
        />
        <span className="d">px</span>
        <button className="fvd-btn primary" disabled={busy || (region.choice === "whole" && !wholeConfirmed)} onClick={run}>
          {busy ? "Measuring…" : stale ? "Update measurement" : "Measure"}
        </button>
      </div>
      {stale && <div className="fvd-ws-note" role="status">Region or edge exclusion changed — update the measurement before export.</div>}
      {result && (
        <div aria-disabled={stale} style={stale ? { opacity: 0.62 } : undefined}>
          <section className="fvd-afm-summary" aria-labelledby="afm-step-summary-title">
            <div className="fvd-afm-section-head">
              <div><h3 id="afm-step-summary-title">Step measurement</h3><span>{resultRegion}</span></div>
              <span className="fvd-afm-count">{(result.n_lower + result.n_upper).toLocaleString()} px</span>
            </div>
            <div className="fvd-afm-summary-grid">
              <div className="fvd-afm-summary-metric primary">
                <span className="k">Step magnitude</span>
                <span className="v">{format(result.height, result.unit)}</span>
                <span className="d">Signed: {format(result.signed_height, result.unit)} along +{result.profile_axis.toUpperCase()}</span>
              </div>
              <div className="fvd-afm-summary-metric">
                <span className="k">Lower terrace scatter</span>
                <span className="v">{format(result.lower_std, result.unit)}</span>
                <span className="d">RMS residual after the shared tilt fit</span>
              </div>
              <div className="fvd-afm-summary-metric">
                <span className="k">Upper terrace scatter</span>
                <span className="v">{format(result.upper_std, result.unit)}</span>
                <span className="d">RMS residual after the shared tilt fit</span>
              </div>
            </div>
          </section>
          <AfmStepEvidence result={result} />
          <div className="fvd-afm-metric-list">
            <div className="fvd-afm-metric-row"><span className="k">Terrace pixels</span><span className="d">lower / upper</span><span className="v">{result.n_lower.toLocaleString()} / {result.n_upper.toLocaleString()}</span></div>
            <div className="fvd-afm-metric-row"><span className="k">Upper terrace</span><span className="d">region balance</span><span className="v">{(result.upper_fraction * 100).toFixed(1)}%</span></div>
            <div className="fvd-afm-metric-row"><span className="k">Edge exclusion</span><span className="d">pixels omitted near the fitted boundary</span><span className="v">{resultEdge} px</span></div>
          </div>
          <div className="fvd-ws-row">
            <button className="fvd-btn" disabled={stale} onClick={() => exportResult("csv")}>Export CSV</button>
            <button className="fvd-btn" disabled={stale} onClick={() => exportResult("json")}>Export JSON</button>
          </div>
        </div>
      )}
    </div>
  );
}
