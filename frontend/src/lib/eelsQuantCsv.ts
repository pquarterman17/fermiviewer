// CSV serialiser for EELS quantification results.
// Operates on the EelsQuantResult shape returned by /api/eels/quantify.
// Pure string builder — no DOM, no store — so it is trivially unit-testable.
//
// Columns: element, atomic_percent, intensity, sigma
// A commented provenance header records image name and edge count.

import type { EelsQuantResult } from "./api";

// ── numeric formatter ─────────────────────────────────────────────────

function num(v: number): string {
  if (!Number.isFinite(v)) return "";
  return String(Number(v.toPrecision(7)));
}

// ── CSV builder ───────────────────────────────────────────────────────

export interface EelsQuantCsvContext {
  imageName: string;
}

/**
 * Serialise an EelsQuantResult to CSV.
 *
 * Columns: element, atomic_percent, intensity, sigma.
 * The provenance header records image name and the number of edges.
 *
 * Reference: Egerton, "Electron Energy-Loss Spectroscopy in the Electron
 * Microscope" 3rd ed. Ch. 5 — Hartree-Slater cross-section quantification.
 * atomic_percent values sum to 100 (within floating-point); intensity is the
 * background-subtracted integrated signal (counts or counts·eV depending on
 * calibration); sigma is the partial cross-section (barns or cm² depending
 * on the route's e0/beta parameters).
 */
export function eelsQuantToCsv(
  r: EelsQuantResult,
  ctx: EelsQuantCsvContext,
): string {
  const n = r.elements.length;
  const lines: string[] = [
    "# fermiviewer EELS quantification export",
    `# image: ${ctx.imageName}`,
    `# n_edges: ${n}`,
    "element,atomic_percent,intensity,sigma",
  ];
  for (let i = 0; i < n; i++) {
    lines.push(
      `${r.elements[i]},${num(r.atomic_percent[i])},${num(r.intensity[i])},${num(r.sigma[i])}`,
    );
  }
  return lines.join("\n") + "\n";
}

/** Strip the extension off a filename for a CSV basename. */
export function csvBaseName(name: string | undefined): string {
  if (!name) return "image";
  return name.replace(/\.[^./\\]+$/, "") || name;
}

/** Trigger a browser download of CSV text. */
export function downloadCsv(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
