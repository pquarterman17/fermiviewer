import type {
  PersistedResultOutput,
  PersistedResultRecord,
} from "../../lib/api";

type SourceLabel = { id: string; name: string; available: boolean };
type ResultAction = "reopen" | "rerun" | "duplicate";

const ANALYSIS_LABELS: Record<string, string> = {
  "eds.quantify": "EDS quantification",
  "eels.quantify": "EELS quantification",
  "measure.profile": "Intensity profile",
  "structure.particles": "Particle analysis",
  "diffraction.index": "Diffraction indexing",
};

function analysisLabel(analysis: string): string {
  return ANALYSIS_LABELS[analysis] ?? analysis
    .split(/[._-]+/)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function analysisMark(analysis: string): string {
  if (analysis.startsWith("eds.")) return "EDS";
  if (analysis.startsWith("eels.")) return "EELS";
  if (analysis.startsWith("structure.")) return "S";
  if (analysis.startsWith("diffraction.")) return "D";
  if (analysis.startsWith("measure.")) return "M";
  return "R";
}

const outputLabel = (name: string): string => name.replaceAll("_", " ");

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "Unknown date";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function finite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function compactNumber(value: number): string {
  return new Intl.NumberFormat(undefined, { maximumSignificantDigits: 4 }).format(value);
}

function scalarValue(output: PersistedResultOutput): {
  value: number;
  sigma: number | null;
  unit: string;
} | null {
  if (output.kind !== "scalar") return null;
  const value = finite(output.data?.["value"]);
  if (value == null) return null;
  return {
    value,
    sigma: finite(output.data?.["sigma"]),
    unit: typeof output.data?.["unit"] === "string" ? output.data["unit"] : "",
  };
}

function paramText(params: Record<string, unknown> | undefined): string[] {
  if (!params) return [];
  const method = params["method"] ?? params["model"] ?? params["quant_method"];
  const beam = params["beam_kv"] ?? params["kv"] ?? params["e0_kv"];
  const text: string[] = [];
  if (typeof method === "string") text.push(method.replaceAll("_", " "));
  if (typeof beam === "number" && Number.isFinite(beam)) text.push(`${compactNumber(beam)} kV`);
  return text;
}

function StatusPill({ result }: { result: PersistedResultRecord }) {
  const degraded = (result.missing_members?.length ?? 0) > 0;
  const status = degraded && result.status === "completed" ? "degraded" : result.status;
  const label = status === "completed" ? "Complete" : status.charAt(0).toUpperCase() + status.slice(1);
  return <span className={`fvd-result-status ${status}`}>{label}</span>;
}

export default function PersistedResultCard({
  result,
  sources,
  derived,
  onSelectSource,
  onAction,
  busyAction,
}: {
  result: PersistedResultRecord;
  sources: SourceLabel[];
  derived?: SourceLabel[];
  onSelectSource?: (id: string) => void;
  onAction?: (action: ResultAction) => void;
  busyAction?: ResultAction | null;
}) {
  const cardTitle = result.label?.trim() || analysisLabel(result.analysis);
  const titleId = `result-${result.id}-title`;
  const outputs = result.outputs ?? [];
  const scalars = outputs
    .map((output) => ({ output, scalar: scalarValue(output) }))
    .filter((item): item is { output: PersistedResultOutput; scalar: NonNullable<ReturnType<typeof scalarValue>> } => item.scalar !== null)
    .slice(0, 6);
  const methods = paramText(result.params);
  const warnings = result.warnings ?? [];
  const missing = result.missing_members ?? [];
  const calibrations = result.calibration ?? [];
  const regions = result.regions ?? [];
  const products = derived ?? [];
  const calibratedAxes = calibrations.flatMap((calibration) =>
    (calibration.axes ?? []).map((axis, index) => ({ axis, index })),
  ).filter(({ axis }) =>
    Number.isFinite(axis.scale) && axis.scale !== 0 && axis.units.trim() !== "",
  );

  return (
    <article className={`fvd-result-card ${result.status}`} aria-labelledby={titleId}>
      <header className="fvd-result-head">
        <div className="fvd-result-mark" aria-hidden="true">
          {analysisMark(result.analysis)}
        </div>
        <div className="fvd-result-title-block">
          <div className="fvd-result-eyebrow">{analysisLabel(result.analysis)}</div>
          <h3 id={titleId}>{cardTitle}</h3>
          <div className="fvd-result-time" title={result.created_at}>{formatDate(result.created_at)}</div>
        </div>
        <StatusPill result={result} />
      </header>

      {result.status !== "completed" && (
        <div className={`fvd-result-message ${result.status}`} role="status">
          <strong>{result.status === "failed" ? "Analysis failed" : "Analysis cancelled"}</strong>
          <span>{result.error || "No reason was recorded."}</span>
        </div>
      )}

      {missing.length > 0 && (
        <div className="fvd-result-message degraded" role="alert">
          <strong>Some saved data is unavailable</strong>
          <span>{missing.length} result payload{missing.length === 1 ? "" : "s"} could not be read. Metadata and provenance are intact.</span>
        </div>
      )}

      {scalars.length > 0 && (
        <div className="fvd-result-metrics" aria-label="Key result values">
          {scalars.map(({ output, scalar }) => (
            <div className="fvd-result-metric" key={output.name}>
              <div className="value">
                {compactNumber(scalar.value)}
                {scalar.sigma != null && <span className="sigma"> ± {compactNumber(scalar.sigma)}</span>}
              </div>
              <div className="unit">{scalar.unit || "unitless"}</div>
              <div className="label">{outputLabel(output.name)}</div>
            </div>
          ))}
        </div>
      )}

      <div className="fvd-result-context">
        <div className="fvd-result-context-row">
          <span className="key">Source</span>
          <div className="fvd-result-source-list">
            {sources.length === 0 ? <span className="missing">Not available in this project</span> : sources.map((source) => (
              <button
                key={source.id}
                className="fvd-result-source"
                disabled={!source.available || !onSelectSource}
                onClick={() => onSelectSource?.(source.id)}
                title={source.available ? `Show ${source.name}` : `${source.name} is unavailable`}
              >
                {source.name}
                {!source.available && <span>missing</span>}
              </button>
            ))}
          </div>
        </div>
        {methods.length > 0 && <div className="fvd-result-context-row"><span className="key">Method</span><span>{methods.join(" · ")}</span></div>}
        {regions.length > 0 && <div className="fvd-result-context-row"><span className="key">Region</span><span>{regions.length} snapshotted region{regions.length === 1 ? "" : "s"}</span></div>}
        {calibrations.length > 0 && (
          <div className="fvd-result-context-row">
            <span className="key">Calibration</span>
            <span>
              {calibratedAxes.map(({ axis, index }) =>
                `${compactNumber(axis.scale)} ${axis.units}/${index < 2 ? "px" : "channel"}`,
              ).join(" · ") || `${calibrations.length} source snapshot${calibrations.length === 1 ? "" : "s"}`}
              {calibrations[0].source ? ` · ${calibrations[0].source}` : ""}
            </span>
          </div>
        )}
        {products.length > 0 && (
          <div className="fvd-result-context-row">
            <span className="key">Produced</span>
            <div className="fvd-result-source-list">
              {products.map((product) => (
                <button key={product.id} className="fvd-result-source" disabled={!product.available || !onSelectSource}
                  onClick={() => onSelectSource?.(product.id)} title={product.available ? `Show ${product.name}` : `${product.name} is unavailable`}>
                  {product.name}{!product.available && <span>missing</span>}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {warnings.length > 0 && (
        <div className="fvd-result-warnings">
          <div className="label">Review notes</div>
          <ul>{warnings.map((warning, index) => <li key={`${warning}-${index}`}>{warning}</li>)}</ul>
        </div>
      )}

      <footer className="fvd-result-footer">
        {onAction && result.status === "completed" && (
          <div className="fvd-result-actions" aria-label="Result actions">
            <button className="fvd-btn primary" disabled={busyAction != null} onClick={() => onAction("reopen")}>Reopen</button>
            <button className="fvd-btn" disabled={busyAction != null} onClick={() => onAction("rerun")}>{busyAction === "rerun" ? "Rerunning…" : "Rerun"}</button>
            <button className="fvd-btn" disabled={busyAction != null} onClick={() => onAction("duplicate")}>Duplicate with changes</button>
          </div>
        )}
        <div className="fvd-result-output-list" aria-label="Saved outputs">
          {outputs.length === 0 ? <span>No scientific outputs</span> : outputs.map((output) => (
            <span className="fvd-result-output" key={`${output.kind}-${output.name}`}>
              {outputLabel(output.name)}<small>{output.kind}</small>
            </span>
          ))}
        </div>
        <details className="fvd-result-provenance">
          <summary>Provenance</summary>
          <dl>
            <dt>Result ID</dt><dd>{result.id}</dd>
            <dt>Analysis</dt><dd>{result.analysis}</dd>
            <dt>FermiViewer</dt><dd>{result.app_version || "Unknown version"}</dd>
            <dt>Parameters</dt><dd><code>{JSON.stringify(result.params ?? {})}</code></dd>
          </dl>
        </details>
      </footer>
    </article>
  );
}
