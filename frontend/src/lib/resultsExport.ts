// Shared structured-results export: turn any tabular analysis result
// (EELS/EDS quant, diffraction d-spacings, grain/particle stats…) into a
// CSV or JSON download. Pure string/object builders — no DOM, no store — so
// they are trivially unit-testable. JSON carries a provenance block (image,
// analysis, params, timestamp) for methods-section reproducibility; CSV keeps
// the commented `#`-header convention used by the original eelsQuantCsv.

export type Cell = string | number | null | undefined;

export interface ResultMeta {
  /** source image filename (provenance) */
  imageName?: string;
  /** analysis name, e.g. "EDS quantification" */
  analysis?: string;
  /** analysis parameters, recorded for reproducibility */
  params?: Record<string, unknown>;
  /** ISO timestamp; defaults to now if omitted */
  timestamp?: string;
}

/** Format a cell for text output (numbers to 7 sig figs; null/NaN → ""). */
function fmt(v: Cell): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "number") {
    return Number.isFinite(v) ? String(Number(v.toPrecision(7))) : "";
  }
  return String(v);
}

/** Quote a CSV field if it contains a comma, quote, or newline. */
function csvField(s: string): string {
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function provenanceLines(meta: ResultMeta | undefined): string[] {
  if (!meta) return [];
  const out: string[] = ["# fermiviewer results export"];
  if (meta.analysis) out.push(`# analysis: ${meta.analysis}`);
  if (meta.imageName) out.push(`# image: ${meta.imageName}`);
  out.push(`# exported: ${meta.timestamp ?? new Date().toISOString()}`);
  for (const [k, v] of Object.entries(meta.params ?? {})) {
    out.push(`# ${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`);
  }
  return out;
}

/** Serialise a table to CSV with an optional commented provenance header. */
export function tableToCsv(
  columns: string[],
  rows: Cell[][],
  meta?: ResultMeta,
): string {
  const lines = [
    ...provenanceLines(meta),
    columns.map((c) => csvField(c)).join(","),
    ...rows.map((r) => r.map((cell) => csvField(fmt(cell))).join(",")),
  ];
  return lines.join("\n") + "\n";
}

/** Serialise a table to JSON: provenance + columns + row objects. */
export function tableToJson(
  columns: string[],
  rows: Cell[][],
  meta?: ResultMeta,
): string {
  const provenance = {
    analysis: meta?.analysis,
    image: meta?.imageName,
    exported: meta?.timestamp ?? new Date().toISOString(),
    params: meta?.params,
  };
  const data = rows.map((r) => {
    const obj: Record<string, Cell> = {};
    columns.forEach((c, i) => {
      obj[c] = r[i] ?? null;
    });
    return obj;
  });
  return JSON.stringify({ provenance, columns, rows: data }, null, 2) + "\n";
}

/** Strip the extension off a filename for an export basename. */
export function exportBaseName(name: string | undefined): string {
  if (!name) return "results";
  return name.replace(/\.[^./\\]+$/, "") || name;
}

/** Trigger a browser download of text content. */
export function downloadText(
  filename: string,
  text: string,
  mime: string,
): void {
  const url = URL.createObjectURL(new Blob([text], { type: mime }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export const downloadCsv = (filename: string, text: string): void =>
  downloadText(filename, text, "text/csv");
export const downloadJson = (filename: string, text: string): void =>
  downloadText(filename, text, "application/json");
