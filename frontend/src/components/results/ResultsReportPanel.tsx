import { useEffect, useMemo, useRef, useState } from "react";

import { buildPersistedResultsReport, type PersistedResultRecord, type ResultsReport } from "../../lib/api";
import { resultsReportHtml } from "../../lib/reportDocument";
import { downloadJson, downloadText } from "../../lib/resultsExport";

interface Props {
  results: PersistedResultRecord[];
  nameOf: (id: string) => string;
}

const labelOf = (result: PersistedResultRecord): string => result.label || result.analysis;
const filenameOf = (title: string): string => `${title.trim().toLocaleLowerCase()
  .replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "fermiviewer-report"}`;

export default function ResultsReportPanel({ results, nameOf }: Props) {
  const available = useMemo(() => results.slice(0, 200), [results]);
  const [selectedIds, setSelectedIds] = useState(() => available.filter((result) => result.status === "completed").map((result) => result.id));
  const [outputNames, setOutputNames] = useState<Record<string, string[]>>(() => Object.fromEntries(
    available.map((result) => [result.id, (result.outputs ?? []).map((output) => output.name)]),
  ));
  const [title, setTitle] = useState("Microscopy analysis report");
  const [note, setNote] = useState("");
  const [includeMethods, setIncludeMethods] = useState(true);
  const [includeCalibration, setIncludeCalibration] = useState(true);
  const [includeWarnings, setIncludeWarnings] = useState(true);
  const [report, setReport] = useState<ResultsReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const previewRef = useRef<HTMLIFrameElement>(null);
  const availableKey = available.map((result) => result.id).join("\u0000");

  useEffect(() => {
    setOutputNames((current) => {
      const next = { ...current };
      for (const result of available) {
        if (!(result.id in next)) next[result.id] = (result.outputs ?? []).map((output) => output.name);
      }
      return next;
    });
  // The joined key updates only when the inventory changes, not on every render.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [availableKey]);

  const byId = useMemo(() => new Map(results.map((result) => [result.id, result])), [results]);
  const selected = selectedIds.map((id) => byId.get(id)).filter(
    (result): result is PersistedResultRecord => Boolean(result),
  );
  const hasOutputForEveryResult = selected.every((result) =>
    (outputNames[result.id] ?? (result.outputs ?? []).map((output) => output.name)).length > 0);
  const sourceNames = useMemo(() => Object.fromEntries(results.flatMap((result) =>
    (result.source_ids ?? []).map((id) => [id, nameOf(id)]))), [nameOf, results]);
  const html = useMemo(() => report ? resultsReportHtml(report, {
    title, note, outputNamesByResult: outputNames, sourceNames,
    includeMethods, includeCalibration, includeWarnings,
  }) : "", [includeCalibration, includeMethods, includeWarnings, note, outputNames, report, sourceNames, title]);

  const toggleResult = (id: string, checked: boolean) => {
    setSelectedIds((current) => checked ? [...current, id] : current.filter((item) => item !== id));
    setReport(null);
  };
  const move = (index: number, delta: -1 | 1) => {
    setSelectedIds((current) => {
      const next = [...current];
      [next[index], next[index + delta]] = [next[index + delta], next[index]];
      return next;
    });
    setReport(null);
  };
  const toggleOutput = (resultId: string, name: string, checked: boolean) => setOutputNames((current) => ({
    ...current,
    [resultId]: checked ? [...(current[resultId] ?? []), name] : (current[resultId] ?? []).filter((item) => item !== name),
  }));
  const build = async () => {
    setBusy(true);
    setError("");
    try {
      setReport(await buildPersistedResultsReport(selectedIds));
    } catch (reason) {
      setReport(null);
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  if (available.length === 0) return <div className="fvd-project-results-empty compact">
    <div className="symbol" aria-hidden="true">▤</div><strong>No results to report</strong>
    <span>Save an analysis first, then return here to compose its figures, tables, calibration, and methods.</span>
  </div>;

  return <div className="fvd-report-workspace">
    <section className="fvd-report-builder" aria-labelledby="report-builder-heading">
      <header><div><span className="fvd-project-results-kicker">COMPOSE</span><h3 id="report-builder-heading">Build a reproducible analysis report</h3></div>
        <span>{selectedIds.length} of {available.length}</span></header>
      <div className="fvd-report-fields">
        <label>Report title<input aria-label="Report title" value={title} onChange={(event) => setTitle(event.target.value)} /></label>
        <label>Context note<textarea aria-label="Report context note" rows={2} value={note} placeholder="Sample, condition, or comparison question…" onChange={(event) => setNote(event.target.value)} /></label>
      </div>
      <div className="fvd-report-option-row" aria-label="Report sections">
        <label><input type="checkbox" checked={includeMethods} onChange={(event) => setIncludeMethods(event.target.checked)} />Methods</label>
        <label><input type="checkbox" checked={includeCalibration} onChange={(event) => setIncludeCalibration(event.target.checked)} />Calibration</label>
        <label><input type="checkbox" checked={includeWarnings} onChange={(event) => setIncludeWarnings(event.target.checked)} />Review notes</label>
      </div>
      <div className="fvd-report-selection-actions">
        <button className="fvd-btn" onClick={() => { setSelectedIds(available.filter((result) => result.status === "completed").map((result) => result.id)); setReport(null); }}>Select all completed</button>
        <button className="fvd-btn" onClick={() => { setSelectedIds([]); setReport(null); }}>Clear</button>
      </div>
      <div className="fvd-report-result-list">{available.map((result) => {
        const index = selectedIds.indexOf(result.id);
        const checked = index >= 0;
        return <div key={result.id} className={`fvd-report-result${checked ? " selected" : ""}`}>
          <label className="fvd-report-result-main"><input type="checkbox" checked={checked} onChange={(event) => toggleResult(result.id, event.target.checked)} />
            <span><strong>{labelOf(result)}</strong><small>{(result.source_ids ?? []).map(nameOf).join(", ") || "No source"} · {result.status}</small></span></label>
          {checked && <div className="fvd-report-order" aria-label={`Order ${labelOf(result)}`}>
            <span>{index + 1}</span><button aria-label={`Move ${labelOf(result)} up`} disabled={index === 0} onClick={() => move(index, -1)}>↑</button>
            <button aria-label={`Move ${labelOf(result)} down`} disabled={index === selectedIds.length - 1} onClick={() => move(index, 1)}>↓</button>
          </div>}
          {checked && (result.outputs?.length ?? 0) > 0 && <div className="fvd-report-outputs">
            {result.outputs?.map((output) => <label key={output.name}><input type="checkbox"
              checked={(outputNames[result.id] ?? []).includes(output.name)}
              onChange={(event) => toggleOutput(result.id, output.name, event.target.checked)} />
              <span>{output.name.replaceAll("_", " ")}<small>{output.kind}</small></span></label>)}
          </div>}
        </div>;
      })}</div>
      {results.length > 200 && <p className="fvd-report-limit-note" role="status">Showing the newest 200 of {results.length} saved results, matching the report limit. Filter or remove older records before reporting them.</p>}
      {!hasOutputForEveryResult && selected.length > 0 && <p className="fvd-report-limit-note" role="alert">Select at least one scientific output for every included result.</p>}
      <button className="fvd-btn primary fvd-report-build" disabled={selected.length === 0 || !hasOutputForEveryResult || busy} onClick={() => void build()}>
        {busy ? "Building preview…" : "Build report preview"}</button>
      {error && <div className="fvd-result-message failed" role="alert"><strong>Report unavailable</strong><span>{error}</span></div>}
    </section>

    {report && <section className="fvd-report-preview" aria-labelledby="report-preview-heading">
      <header><div><span className="fvd-project-results-kicker">PREVIEW</span><h3 id="report-preview-heading">Publication-ready layout</h3></div>
        <div><button className="fvd-btn" onClick={() => previewRef.current?.contentWindow?.print()}>Print / Save PDF</button>
          <button className="fvd-btn" onClick={() => downloadText(`${filenameOf(title)}.html`, html, "text/html")}>Export HTML</button>
          <button className="fvd-btn" title="Manifest only; large arrays still require the originating project"
            onClick={() => downloadJson(`${filenameOf(title)}-manifest.json`, `${JSON.stringify(report, null, 2)}\n`)}>Manifest JSON</button></div></header>
      <p className="fvd-report-manifest-note">HTML and print use the composed layout below. The JSON option is a manifest, not a self-contained data bundle; large stored arrays still require the project.</p>
      <iframe ref={previewRef} className="fvd-report-frame" title="Analysis report preview" srcDoc={html} />
    </section>}
  </div>;
}
