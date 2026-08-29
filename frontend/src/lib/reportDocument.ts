import type { ReportOutput, ReportResult, ResultsReport } from "./api";

export interface ReportDocumentOptions {
  title: string;
  note: string;
  outputNamesByResult: Record<string, string[]>;
  sourceNames: Record<string, string>;
  includeMethods: boolean;
  includeCalibration: boolean;
  includeWarnings: boolean;
}

const escapeHtml = (value: unknown): string => String(value ?? "")
  .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;").replaceAll("'", "&#039;");

const number = (value: unknown): string => {
  if (value === null) return "not finite";
  if (typeof value !== "number") return value === undefined ? "not recorded" : escapeHtml(value);
  if (!Number.isFinite(value)) return "not finite";
  return Number.isInteger(value) ? String(value) : String(Number(value.toPrecision(7)));
};

const unitText = (value: unknown, dimensionless: boolean): string => typeof value !== "string" || (value === "" && !dimensionless)
  ? "unit not recorded" : value === "" ? "dimensionless" : value;

const timestamp = (value: string): string => {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toISOString();
};

const rowsOf = (output: ReportOutput): unknown[][] => {
  const inlineRows = output.data?.rows;
  if (Array.isArray(inlineRows) && inlineRows.every(Array.isArray)) return inlineRows as unknown[][];
  if (Array.isArray(output.values) && output.values.every(Array.isArray)) return output.values as unknown[][];
  return [];
};

function curveSvg(output: ReportOutput): string {
  const rows = rowsOf(output).filter((row) => row.length >= 2 &&
    typeof row[0] === "number" && Number.isFinite(row[0]) && typeof row[1] === "number" && Number.isFinite(row[1]));
  if (rows.length < 2) return "";
  const xs = rows.map((row) => row[0] as number);
  const ys = rows.map((row) => row[1] as number);
  const [xmin, xmax] = [Math.min(...xs), Math.max(...xs)];
  const [ymin, ymax] = [Math.min(...ys), Math.max(...ys)];
  const xspan = xmax - xmin || 1;
  const yspan = ymax - ymin || 1;
  const points = rows.map((row) => {
    const x = 34 + (((row[0] as number) - xmin) / xspan) * 526;
    const y = 16 + (1 - ((row[1] as number) - ymin) / yspan) * 154;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(" ");
  return `<svg class="curve" viewBox="0 0 576 194" role="img" aria-label="${escapeHtml(output.name)} curve">
    <line x1="34" y1="170" x2="560" y2="170"/><line x1="34" y1="16" x2="34" y2="170"/>
    <polyline points="${points}"/><text x="34" y="188">${number(xmin)}</text><text x="560" y="188" text-anchor="end">${number(xmax)}</text>
    <text x="28" y="22" text-anchor="end">${number(ymax)}</text><text x="28" y="170" text-anchor="end">${number(ymin)}</text></svg>`;
}

function unavailableOutput(output: ReportOutput, result: ReportResult, noun: "Curve" | "Table"): string {
  const missing = new Set(result.missing_members ?? []);
  if (output.values_inlined === true || Array.isArray(output.data?.rows)) {
    return noun === "Table" ? "0 rows were recorded." : "Too few finite points are available to plot this curve.";
  }
  const shape = output.shape?.join(" × ") || "unknown shape";
  if (output.member && !missing.has(output.member)) {
    return `Values exceed the report inline limit and are cited as project member ${output.member} (${shape}, ${output.dtype || "unknown dtype"}).`;
  }
  return "This array was missing or unreadable when the project loaded; the saved record is degraded.";
}

function outputHtml(output: ReportOutput, result: ReportResult): string {
  const caption = output.caption ? `<p class="caption">${escapeHtml(output.caption)}</p>` : "";
  if (output.kind === "scalar") {
    const value = number(output.data?.value);
    const sigma = typeof output.data?.sigma === "number" ? ` ± ${number(output.data.sigma)}` : "";
    const unit = unitText(output.data?.unit, output.data?.dimensionless === true);
    return `<div class="metric"><div>${value}<small>${sigma} · ${escapeHtml(unit)}</small></div><span>${escapeHtml(output.name.replaceAll("_", " "))}</span>${caption}</div>`;
  }
  if (output.kind === "curve" || output.kind === "fit") {
    const svg = curveSvg(output);
    return `<section class="output"><h3>${escapeHtml(output.name)}</h3>${svg || `<p class="unavailable">${escapeHtml(unavailableOutput(output, result, "Curve"))}</p>`}${caption}</section>`;
  }
  if (output.kind === "table") {
    const rows = rowsOf(output);
    const columns = Array.isArray(output.data?.columns) ? output.data.columns : [];
    if (rows.length === 0) return `<section class="output"><h3>${escapeHtml(output.name)}</h3><p class="unavailable">${escapeHtml(unavailableOutput(output, result, "Table"))}</p>${caption}</section>`;
    const units = Array.isArray(output.data?.units) ? output.data.units : [];
    const dimensionless = output.data?.dimensionless === true;
    const head = columns.length > 0 ? `<thead><tr>${columns.map((column, index) => `<th>${escapeHtml(column)}<small>${escapeHtml(unitText(units[index], dimensionless))}</small></th>`).join("")}</tr></thead>` : "";
    const body = rows.map((row) => `<tr>${row.map((cell) => `<td>${number(cell)}</td>`).join("")}</tr>`).join("");
    return `<section class="output"><h3>${escapeHtml(output.name)}</h3><div class="table-wrap"><table>${head}<tbody>${body}</tbody></table></div>${caption}</section>`;
  }
  return `<section class="output"><h3>${escapeHtml(output.name)}</h3><div class="output-kind">${escapeHtml(output.kind)}</div>${caption}</section>`;
}

function resultHtml(result: ReportResult, options: ReportDocumentOptions): string {
  const selected = new Set(options.outputNamesByResult[result.id] ?? (result.outputs ?? []).map((output) => output.name));
  const outputs = (result.outputs ?? []).filter((output) => selected.has(output.name));
  const scalar = outputs.filter((output) => output.kind === "scalar");
  const other = outputs.filter((output) => output.kind !== "scalar");
  const sources = (result.source_ids ?? []).map((id) => options.sourceNames[id] ?? id).join(", ");
  const degraded = (result.missing_members ?? []).length > 0;
  return `<section class="result ${escapeHtml(result.status)}">
    <header><div><span class="eyebrow">${escapeHtml(result.analysis)}</span><h2>${escapeHtml(result.label || result.analysis)}</h2></div><time>${escapeHtml(timestamp(result.created_at))}</time></header>
    <p class="source">Source: ${escapeHtml(sources || "No source recorded")} · Result ${escapeHtml(result.id)} · FermiViewer ${escapeHtml(result.app_version || "unknown")}</p>
    ${result.status !== "completed" ? `<div class="status-banner"><strong>${escapeHtml(result.status.toUpperCase())}</strong> — ${escapeHtml(result.error || "No reason was recorded.")}</div>` : ""}
    ${degraded ? `<div class="status-banner"><strong>DEGRADED</strong> — ${escapeHtml(String(result.missing_members?.length))} stored member array(s) were missing or unreadable.</div>` : ""}
    ${outputs.length === 0 ? `<p class="unavailable">No scientific outputs were selected for this result.</p>` : ""}
    ${scalar.length > 0 ? `<div class="metrics">${scalar.map((output) => outputHtml(output, result)).join("")}</div>` : ""}
    ${other.map((output) => outputHtml(output, result)).join("")}
    <details><summary>Parameters and provenance</summary><pre>${escapeHtml(JSON.stringify(result.params ?? {}, null, 2))}</pre></details>
  </section>`;
}

export function resultsReportHtml(report: ResultsReport, options: ReportDocumentOptions): string {
  const calibration = report.calibration.map((entry) => `<tr><td>${escapeHtml(options.sourceNames[entry.image_id] ?? entry.image_id)}</td><td>${entry.consistent ? "Consistent" : "Multiple recorded states"}</td><td>${entry.variants.map((variant) => variant.axes.filter((axis) => axis.calibrated && axis.scale != null).map((axis) => `${number(axis.scale)} ${escapeHtml(axis.units)}/${axis.index < 2 ? "px" : "channel"}`).join(" · ") || "Uncalibrated").join("; ")}</td></tr>`).join("");
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escapeHtml(options.title)}</title><style>
    :root{color:#20232a;background:#eef0f4;font:14px/1.5 Inter,Segoe UI,Arial,sans-serif}*{box-sizing:border-box}body{margin:0;padding:30px}.sheet{max-width:900px;margin:auto;padding:54px 62px;background:#fff;box-shadow:0 12px 42px #18203220}.report-head{padding-bottom:24px;border-bottom:2px solid #7257b7}.kicker,.eyebrow{color:#7257b7;font-size:10px;font-weight:700;letter-spacing:.12em;text-transform:uppercase}h1{margin:5px 0 8px;font-size:30px;line-height:1.15}h2{margin:3px 0;font-size:19px}h3{margin:0 0 8px;font-size:14px}.meta,.source,.caption,.unavailable{color:#626875;font-size:12px}.note{margin:18px 0 0;padding:12px 14px;border-left:3px solid #7257b7;background:#f6f3fc;white-space:pre-wrap}.result{break-inside:avoid;margin-top:32px}.result>header{display:flex;justify-content:space-between;gap:18px;padding-bottom:9px;border-bottom:1px solid #dfe2e8}.result time{color:#777d88;font-size:11px}.status-banner{margin:10px 0;padding:9px 11px;border-left:3px solid #a13f45;background:#fff0f1;color:#702b30}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin:14px 0}.metric{padding:12px;border:1px solid #dfe2e8;background:#fafbfc}.metric div{font:18px ui-monospace,SFMono-Regular,Consolas,monospace}.metric small,.metric .caption{color:#626875;font-size:10px}.metric span{display:block;margin-top:5px;color:#777d88;font-size:9px;text-transform:uppercase}.output{margin:18px 0}.output-kind{display:inline-block;padding:3px 7px;border:1px solid #dfe2e8;border-radius:99px;color:#626875;font-size:10px;text-transform:uppercase}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;font-size:11px}th,td{padding:6px 8px;border:1px solid #dfe2e8;text-align:left}th{background:#f4f5f8}th small{display:block;color:#777d88;font-size:8px;font-weight:400}.curve{display:block;width:100%;max-height:270px;background:#fafbfc}.curve line{stroke:#aeb3bd;stroke-width:1}.curve polyline{fill:none;stroke:#7257b7;stroke-width:2}.curve text{fill:#777d88;font-size:9px}.warnings{margin:24px 0;padding:14px 18px;border-left:3px solid #b37a23;background:#fff8ec}.warnings h2{font-size:14px}.warnings ul{margin:7px 0 0;padding-left:18px}.calibration{margin-top:28px}.methods{margin-top:34px;break-before:auto}.methods p{white-space:pre-wrap}details{margin-top:12px;color:#626875;font-size:10px}pre{overflow:auto;padding:9px;background:#f4f5f8;font-size:9px}.report-foot{margin-top:40px;padding-top:12px;border-top:1px solid #dfe2e8;color:#777d88;font-size:10px}@media(max-width:680px){body{padding:0}.sheet{padding:28px 22px;box-shadow:none}.result>header{display:block}.result time{display:block;margin-top:4px}}@media print{:root{background:#fff}body{padding:0}.sheet{max-width:none;padding:0;box-shadow:none}details{display:none}@page{margin:16mm}}
  </style></head><body><main class="sheet"><header class="report-head"><div class="kicker">FERMIVIEWER ANALYSIS REPORT</div><h1>${escapeHtml(options.title)}</h1><div class="meta">Generated ${escapeHtml(timestamp(report.generated_at))} · FermiViewer ${escapeHtml(report.app_version)}</div>${options.note.trim() ? `<div class="note">${escapeHtml(options.note.trim())}</div>` : ""}</header>
  ${options.includeWarnings && report.warnings.length > 0 ? `<aside class="warnings"><h2>Review notes</h2><ul>${report.warnings.map((warning) => `<li>${escapeHtml(warning)}</li>`).join("")}</ul></aside>` : ""}
  ${report.results.map((result) => resultHtml(result, options)).join("")}
  ${options.includeCalibration && calibration ? `<section class="calibration"><h2>Calibration summary</h2><table><thead><tr><th>Source</th><th>Status</th><th>Recorded calibration</th></tr></thead><tbody>${calibration}</tbody></table></section>` : ""}
  ${options.includeMethods ? `<section class="methods"><h2>Methods</h2><p>${escapeHtml(report.methods)}</p></section>` : ""}
  <footer class="report-foot">Report manifest v${escapeHtml(report.version)}. Large member-backed arrays may require the originating FermiViewer project.</footer></main></body></html>`;
}
