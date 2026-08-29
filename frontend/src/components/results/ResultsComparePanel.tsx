import { useEffect, useMemo, useState } from "react";

import {
  comparePersistedResults,
  type PersistedResultOutput,
  type PersistedResultRecord,
  type ResultComparison,
} from "../../lib/api";

interface Props {
  results: PersistedResultRecord[];
  nameOf: (id: string) => string;
}

const labelOf = (result: PersistedResultRecord): string =>
  result.label || result.analysis.split(/[._-]+/).map((part) =>
    part.charAt(0).toUpperCase() + part.slice(1)).join(" ");

const outputOf = (record: PersistedResultRecord, name: string): PersistedResultOutput | undefined =>
  record.outputs?.find((output) => output.name === name);

const compact = (value: number): string => new Intl.NumberFormat(undefined, {
  maximumSignificantDigits: 6,
}).format(value);

function OutputValue({ output }: { output?: PersistedResultOutput }) {
  if (!output) return <span className="fvd-compare-missing">Not recorded</span>;
  if (output.kind !== "scalar") return <span className="fvd-compare-kind">{output.kind}</span>;
  const value = output.data?.value;
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return <span className="fvd-compare-missing">Unavailable</span>;
  }
  const sigma = output.data?.sigma;
  const unit = typeof output.data?.unit === "string" ? output.data.unit : "";
  return <span className="fvd-compare-value">{compact(value)}
    {typeof sigma === "number" && Number.isFinite(sigma) && <small> ± {compact(sigma)}</small>}
    {unit && <small> {unit}</small>}
  </span>;
}

export default function ResultsComparePanel({ results, nameOf }: Props) {
  const completed = useMemo(() => results.filter((result) => result.status === "completed"), [results]);
  const [referenceId, setReferenceId] = useState(completed[0]?.id ?? "");
  const [comparison, setComparison] = useState<ResultComparison | null>(null);
  const [selected, setSelected] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (completed.some((result) => result.id === referenceId)) return;
    setReferenceId(completed[0]?.id ?? "");
  }, [completed, referenceId]);

  const completedKey = completed.map((result) => result.id).join("\u0000");
  useEffect(() => {
    if (!referenceId || completed.length < 2) {
      setComparison(null);
      setSelected(null);
      setBusy(false);
      return;
    }
    const controller = new AbortController();
    setBusy(true);
    setError("");
    void comparePersistedResults(referenceId, undefined, controller.signal)
      .then((next) => {
        setComparison(next);
        const ids = next.compatible.map((match) => match.id);
        setSelected((current) => {
          if (current === null) return ids;
          const kept = current.filter((id) => ids.includes(id));
          return kept.length === 0 && current.length > 0 ? ids : kept;
        });
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setComparison(null);
        setSelected(null);
        setError(reason instanceof Error ? reason.message : String(reason));
      })
      .finally(() => {
        if (!controller.signal.aborted) setBusy(false);
      });
    return () => controller.abort();
  }, [completed.length, completedKey, referenceId]);

  const byId = useMemo(() => new Map(results.map((result) => [result.id, result])), [results]);
  const reference = byId.get(referenceId);
  const selectedIds = selected ?? [];
  const selectedMatches = comparison?.compatible.filter((match) => selectedIds.includes(match.id)) ?? [];
  const unverifiedOutputs = new Set((comparison?.notes ?? []).flatMap((note) => {
    const match = /^output '([^']+)': units not verified/.exec(note);
    return match ? [match[1]] : [];
  }));
  const commonOutputs = reference?.outputs?.map((output) => output.name).filter((name) =>
    selectedMatches.every((match) => match.outputs.includes(name))) ?? [];
  const columns = reference ? [reference, ...selectedMatches.map((match) => byId.get(match.id)).filter(
    (record): record is PersistedResultRecord => Boolean(record),
  )] : [];

  if (completed.length < 2) return <div className="fvd-project-results-empty compact">
    <div className="symbol" aria-hidden="true">⇄</div><strong>Two completed results are needed</strong>
    <span>Save another run to compare outputs, units, and calibration context side by side.</span>
  </div>;

  return <div className="fvd-compare-workspace">
    <div className="fvd-compare-reference">
      <div><span className="fvd-project-results-kicker">REFERENCE</span>
        <h3>Choose the result others should be compared against</h3></div>
      <label>Reference result<select aria-label="Reference result" value={referenceId}
        onChange={(event) => { setSelected(null); setReferenceId(event.target.value); }}>
        {completed.map((result) => <option key={result.id} value={result.id}>{labelOf(result)}</option>)}
      </select></label>
    </div>

    {busy && <div className="fvd-compare-loading" role="status">Checking scientific compatibility…</div>}
    {error && <div className="fvd-result-message failed" role="alert"><strong>Comparison unavailable</strong><span>{error}</span></div>}
    {comparison && !busy && <>
      <section className="fvd-compare-candidates" aria-labelledby="compare-candidates-heading">
        <header><div><span className="fvd-project-results-kicker">COMPARABLE SET</span>
          <h3 id="compare-candidates-heading">Select results to place beside the reference</h3></div>
          <span>{selectedIds.length} selected</span></header>
        {comparison.compatible.length === 0 ? <p className="fvd-compare-empty">No compatible results were found for this reference.</p>
          : <div className="fvd-compare-choice-list">{comparison.compatible.map((match) => {
            const record = byId.get(match.id);
            const agreement = match.calibration_agreement;
            const calibration = agreement.verified ? (agreement.agrees ? "Calibration matched" : "Calibration differs") : "Calibration not verified";
            return <label key={match.id} className="fvd-compare-choice">
              <input type="checkbox" checked={selectedIds.includes(match.id)} onChange={(event) => setSelected((current) =>
                event.target.checked ? [...(current ?? []), match.id] : (current ?? []).filter((id) => id !== match.id))} />
              <span><strong>{record ? labelOf(record) : match.id}</strong>
                <small>{record?.source_ids?.map(nameOf).join(", ") || "No source"} · {match.outputs.length} shared output{match.outputs.length === 1 ? "" : "s"}</small></span>
              <span className={`fvd-compare-calibration ${agreement.verified && !agreement.agrees ? "warn" : ""}`}>{calibration}</span>
            </label>;
          })}</div>}
      </section>

      {columns.length > 1 && <section className="fvd-compare-matrix" aria-labelledby="compare-matrix-heading">
        <header><div><span className="fvd-project-results-kicker">SIDE BY SIDE</span>
          <h3 id="compare-matrix-heading">Shared scientific outputs</h3></div>
          <span>{commonOutputs.length} shared</span></header>
        {commonOutputs.length === 0 ? <p className="fvd-compare-empty">This selection is pairwise compatible, but has no single output shared by every result.</p>
          : <div className="fvd-compare-table-wrap"><table className="fvd-compare-table">
            <thead><tr><th>Output</th>{columns.map((record, index) => <th key={record.id}>
              <span>{index === 0 ? "Reference" : `Result ${index}`}</span>{labelOf(record)}</th>)}</tr></thead>
            <tbody>{commonOutputs.map((name) => <tr key={name}><th>{name.replaceAll("_", " ")}
              {unverifiedOutputs.has(name) && <span className="fvd-compare-unit-note" title="The unit was not recorded or could not be verified">units not verified</span>}</th>
              {columns.map((record) => <td key={record.id}><OutputValue output={outputOf(record, name)} /></td>)}</tr>)}</tbody>
          </table></div>}
      </section>}

      {(comparison.notes.length > 0 || comparison.rejected.length > 0) && <details className="fvd-compare-review">
        <summary>Compatibility review <span>{comparison.notes.length + comparison.rejected.length}</span></summary>
        {comparison.notes.length > 0 && <div><strong>Scientific notes</strong><ul>{comparison.notes.map((note) => <li key={note}>{note}</li>)}</ul></div>}
        {comparison.rejected.length > 0 && <div><strong>Not comparable</strong><ul>{comparison.rejected.map((item) =>
          <li key={item.id}><b>{byId.get(item.id) ? labelOf(byId.get(item.id)!) : item.id}</b> — {item.message}</li>)}</ul></div>}
      </details>}
    </>}
  </div>;
}
