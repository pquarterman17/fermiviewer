// Project Compare workshop (W4 item 24) — THE result-vs-parameter
// deliverable: for each sample group, aggregate its member images' region
// areas (lib/regionTable.ts, item 15) against a chosen numeric parameter
// (item 23's SampleParamsEditor, embedded below for the currently selected
// sample), producing a table + plot with error bars, exportable as CSV via
// lib/resultsExport.ts. Pure aggregation lives in lib/projectCompare.ts —
// this component only wires store selectors, local UI state, and the
// export button around it.
//
// Mounted as ToolKind "projectcompare" (Analysis ▸ Samples ▸ Compare
// Samples…, components/Shell/menus/analysisMenu.ts) rather than a slot
// inside Library/SampleSection.tsx or Filmstrip.tsx — both are owned by
// another in-flight change on this branch. This is the reachable path for
// both item 23 (parameter editing, via the embedded editor) and item 24
// (this panel) today.
//
// docs/schema/fvp-v2.schema.json's `primary_param` names the intended
// x-axis so a saved project needs no per-use prompt, but nothing in the
// frontend reads the manifest yet (routes/session_io.py and io/project_*.py
// are out of scope here) — the parameter dropdown below defaults to the
// first parameter name (alphabetical) and remembers the user's choice for
// the session; wiring it to `primary_param` is a small follow-up once the
// project-file frontend integration lands.

import { useEffect, useMemo, useState } from "react";

import { formatPlusMinus } from "../../lib/formatUncertainty";
import {
  compareCsvColumns,
  compareCsvRows,
  compareSamplesByParam,
  paramColumn,
} from "../../lib/projectCompare";
import { downloadCsv, tableToCsv } from "../../lib/resultsExport";
import { useViewer } from "../../store/viewer";
import SampleParamsEditor from "../Library/SampleParamsEditor";
import ResultVsParamPlot from "../plots/ResultVsParamPlot";

export default function ProjectComparePanel() {
  const imageGroups = useViewer((s) => s.imageGroups);
  const images = useViewer((s) => s.images);
  const measures = useViewer((s) => s.measures);

  // A "sample" is any group with member images — a purely organisational
  // project group (holding only sub-samples) has nothing to edit or plot.
  const samples = useMemo(() => imageGroups.filter((g) => g.ids.length > 0), [imageGroups]);

  const paramNames = useMemo(() => {
    const names = new Set<string>();
    for (const g of samples) for (const k of Object.keys(g.params ?? {})) names.add(k);
    return [...names].sort();
  }, [samples]);

  const [paramName, setParamName] = useState<string | null>(null);
  const [selectedSampleId, setSelectedSampleId] = useState<string | null>(null);

  useEffect(() => {
    if (paramName && paramNames.includes(paramName)) return;
    setParamName(paramNames[0] ?? null);
  }, [paramName, paramNames]);

  useEffect(() => {
    if (selectedSampleId && samples.some((s) => s.id === selectedSampleId)) return;
    setSelectedSampleId(samples[0]?.id ?? null);
  }, [selectedSampleId, samples]);

  const result = useMemo(
    () => (paramName ? compareSamplesByParam(samples, images, measures, paramName) : null),
    [samples, images, measures, paramName],
  );

  const onExport = () => {
    if (!result || result.rows.length === 0) return;
    const csv = tableToCsv(compareCsvColumns(result), compareCsvRows(result.rows), {
      analysis: "Sample comparison",
      params: { parameter: result.paramName },
    });
    downloadCsv(`sample_comparison_${result.paramName}.csv`, csv);
    useViewer.getState().setStatus(
      `exported ${result.rows.length} sample(s) vs ${result.paramName} to CSV`,
    );
  };

  if (samples.length === 0) {
    return (
      <div className="fvd-ws">
        <div className="fvd-ws-note">
          No sample groups yet — group images into named samples (Library)
          and give them parameters before comparing results across samples.
        </div>
      </div>
    );
  }

  return (
    <div className="fvd-ws" data-testid="project-compare-panel">
      <div className="fvd-ws-section">Sample parameters</div>
      <div className="fvd-ws-row">
        <span className="k">Sample</span>
        <select
          aria-label="Sample to edit"
          value={selectedSampleId ?? ""}
          onChange={(e) => setSelectedSampleId(e.target.value)}
        >
          {samples.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </div>
      {selectedSampleId && <SampleParamsEditor groupId={selectedSampleId} />}

      <div className="fvd-ws-section">Result vs parameter</div>
      <div className="fvd-ws-row">
        <span className="k">Parameter</span>
        <select
          aria-label="Parameter to plot"
          value={paramName ?? ""}
          onChange={(e) => setParamName(e.target.value)}
          disabled={paramNames.length === 0}
        >
          {paramNames.length === 0 ? (
            <option value="">no parameters yet</option>
          ) : (
            paramNames.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))
          )}
        </select>
      </div>

      {result && result.rows.length > 0 && (
        <>
          <ResultVsParamPlot
            rows={result.rows}
            paramName={result.paramName}
            resultUnit={result.resultUnit}
          />
          <table className="fvd-ws-table">
            <thead>
              <tr>
                <th>Sample</th>
                <th>{paramColumn(result.paramName, result.rows[0].paramUnit)}</th>
                <th>n</th>
                <th>area {result.resultUnit ? `(${result.resultUnit}²)` : ""} mean ± sd</th>
              </tr>
            </thead>
            <tbody>
              {result.rows.map((r) => (
                <tr key={r.groupId}>
                  <td>{r.sampleName}</td>
                  <td>{r.paramValue}</td>
                  <td>{r.n}</td>
                  <td>{formatPlusMinus(r.mean, r.std, 3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="fvd-ws-row">
            <button className="fvd-btn" onClick={onExport}>
              Export CSV
            </button>
          </div>
        </>
      )}

      {result && result.rows.length === 0 && paramName && (
        <div className="fvd-ws-note" style={{ color: "var(--text-faint)" }}>
          No sample has a usable "{paramName}" value + measured area yet.
        </div>
      )}

      {result && result.excluded.length > 0 && (
        <div className="fvd-ws-note" style={{ color: "var(--text-faint)" }}>
          {result.excluded.length} sample(s) excluded:
          <ul>
            {result.excluded.map((e) => (
              <li key={e.groupId}>
                {e.sampleName}: {e.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
