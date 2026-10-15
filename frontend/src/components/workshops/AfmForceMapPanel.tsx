import { useEffect, useRef, useState, type CSSProperties } from "react";

import {
  runJob, startForceMapsJob, type ForceMapMetric, type ForceMapsResult,
  type ForceMeta, type ForceSettings,
} from "../../lib/api";
import { downloadCsv, downloadJson, exportBaseName, tableToCsv, type Cell } from "../../lib/resultsExport";
import { useViewer } from "../../store/viewer";

const METRICS: { key: ForceMapMetric; label: string }[] = [
  { key: "youngs_modulus", label: "Modulus" }, { key: "adhesion", label: "Adhesion" },
  { key: "contact_z", label: "Contact height" }, { key: "fit_r2", label: "Fit R²" },
  { key: "fit_rms", label: "Residual RMS" },
];

function rows(result: ForceMapsResult, meta: ForceMeta): Cell[][] {
  const columns = meta.grid?.[1] ?? result.n;
  const [dy, dx] = meta.map_pitch_nm ?? [null, null];
  return result.table.youngs_modulus.map((_, index) => [
    index + 1, Math.floor(index / columns) + 1, index % columns + 1,
    dx === null ? null : (index % columns) * dx,
    dy === null ? null : Math.floor(index / columns) * dy,
    result.table.accepted[index] ? "accepted" : "rejected",
    result.table.youngs_modulus[index], result.table.adhesion[index],
    result.table.contact_z[index], result.table.max_force[index], result.table.fit_r2[index],
    result.table.fit_rms[index], result.table.fit_points[index], result.table.residual_lag1[index],
  ]);
}

export default function AfmForceMapPanel({
  meta, settings, onBusyChange, onSelectCurve,
}: {
  meta: ForceMeta; settings: ForceSettings;
  onBusyChange: (busy: boolean) => void; onSelectCurve: (index: number) => void;
}) {
  const ingestDerived = useViewer((state) => state.ingestDerived);
  const setStatus = useViewer((state) => state.setStatus);
  const [result, setResult] = useState<ForceMapsResult | null>(null);
  const [metric, setMetric] = useState<ForceMapMetric>("youngs_modulus");
  const [progress, setProgress] = useState<{ fraction: number; message: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [resultKey, setResultKey] = useState("");
  const [resultSettings, setResultSettings] = useState<ForceSettings>(settings);
  const controller = useRef<AbortController | null>(null);
  const currentMetaId = useRef(meta.id);
  currentMetaId.current = meta.id;

  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => { setResult(null); setError(null); }, [meta.id]);

  const run = () => {
    const source = meta;
    const runSettings = { ...settings };
    const abort = new AbortController();
    controller.current = abort;
    onBusyChange(true);
    setError(null);
    setProgress({ fraction: 0, message: "Queued" });
    void runJob<ForceMapsResult>(
      () => startForceMapsJob(source.id, runSettings),
      (fraction, message) => setProgress({ fraction, message }), 250, abort.signal,
    ).then((next) => {
      if (currentMetaId.current === source.id) {
        setResult(next);
        setResultKey(JSON.stringify([source.id, runSettings]));
        setResultSettings(runSettings);
      }
      if (next.images.length) ingestDerived(next.images);
      setStatus(`${source.name}: ${next.accepted}/${next.n} accepted fits · ${next.rejected} rejected`);
    }).catch((reason: Error) => {
      if (reason.message !== "cancelled") setError(reason.message);
    }).finally(() => {
      if (controller.current === abort) controller.current = null;
      setProgress(null);
      onBusyChange(false);
    });
  };

  const exportRows = (kind: "csv" | "json") => {
    if (!result || stale) return;
    const base = `${exportBaseName(meta.name)}_force_map`;
    const columns = ["curve", "row", "column", "x_nm", "y_nm", "quality",
      "youngs_modulus_Pa", "adhesion_nN", "contact_z_nm",
      "max_force_nN", "fit_r2", "fit_rms_nN", "fit_points", "residual_lag1"];
    const provenance = { analysis: "AFM force map", imageName: meta.name,
      params: { ...resultSettings, grid: meta.grid, mapPitchNm: meta.map_pitch_nm } };
    if (kind === "csv") downloadCsv(`${base}.csv`, tableToCsv(columns, rows(result, meta), provenance));
    else downloadJson(`${base}.json`, `${JSON.stringify({ provenance, ...result }, null, 2)}\n`);
  };

  const grid = result?.grids?.[metric] ?? null;
  const flat = grid?.flat().filter((value): value is number => value !== null) ?? [];
  const lo = flat.length ? Math.min(...flat) : 0;
  const span = flat.length ? Math.max(...flat) - lo || 1 : 1;
  const stale = result !== null && resultKey !== JSON.stringify([meta.id, settings]);

  return <section className="fvd-afm-map-panel" aria-labelledby="afm-map-title">
    <div className="fvd-afm-section-head"><div><h3 id="afm-map-title">Force map</h3><span>Every pixel remains linked to its source curve</span></div></div>
    <div className="fvd-ws-row">
      {!progress && <button className="fvd-btn primary" onClick={run}>Analyse map</button>}
      {progress && <><progress value={progress.fraction} max={1} aria-label="Force-map progress" /><span>{Math.round(progress.fraction * 100)}% · {progress.message}</span><button className="fvd-btn" onClick={() => controller.current?.abort()}>Cancel</button></>}
    </div>
    {error && <div className="fvd-ws-note" role="alert">Force map: {error}</div>}
    {stale && <div className="fvd-ws-note" role="status">Analysis controls changed — rerun the map before export.</div>}
    {result && <>
      <div className="fvd-afm-map-summary"><strong>{result.accepted} accepted</strong><span>{result.rejected} rejected</span><span>{result.failed} failed</span><span>Median E {result.summaries.youngs_modulus.median?.toPrecision(3) ?? "—"} Pa</span></div>
      {grid && <>
        <div className="fvd-ws-row"><label htmlFor="force-map-layer">Inspect layer</label><select id="force-map-layer" value={metric} onChange={(event) => setMetric(event.target.value as ForceMapMetric)}>{METRICS.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</select><span>Click a pixel to inspect its curve</span></div>
        <div className="fvd-afm-map-grid" style={{ gridTemplateColumns: `repeat(${grid[0]?.length ?? 1}, 1fr)` }} role="grid" aria-label={`${METRICS.find((item) => item.key === metric)?.label} force map`}>
          {grid.flatMap((row, rowIndex) => row.map((value, colIndex) => {
            const index = rowIndex * row.length + colIndex;
            const accepted = result.grids?.accepted[rowIndex]?.[colIndex] ?? false;
            const alpha = value === null ? 0 : 0.18 + 0.72 * (value - lo) / span;
            return <button key={`${rowIndex}-${colIndex}`} role="gridcell" disabled={progress !== null} className={accepted ? "" : "rejected"} style={{ "--map-alpha": alpha } as CSSProperties} title={`curve ${index + 1}: ${value ?? "no value"}${accepted ? "" : " · rejected"}`} onClick={() => onSelectCurve(index)}>{accepted ? "" : "×"}</button>;
          }))}
        </div>
      </>}
      <div className="fvd-ws-row"><button className="fvd-btn" disabled={stale || progress !== null} onClick={() => exportRows("csv")}>Export numeric CSV</button><button className="fvd-btn" disabled={stale || progress !== null} onClick={() => exportRows("json")}>Export grids + provenance</button></div>
    </>}
  </section>;
}
