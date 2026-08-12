// CSV serialiser for spectral model-fit REPORTS
// (ANALYSIS_PRESENTATION_PLAN.md #7 / audit R8): the fitted parameters ±
// 1σ and fit-quality stats (R², χ²ᵣ, fit window) for the model fits
// themselves — /eels/fit (EelsFitResult) and /eds/peakfit or its ζ-factor
// sibling /eds/zeta (EdsPeakfitResult | EdsZetaResult).
//
// Distinct from lib/edsQuantCsv.ts / lib/eelsQuantCsv.ts, which export the
// QUANTIFICATION tables (composition, keyed on at%/wt%, plus the ζ
// mass-thickness/artifact trail). This export's row is the fitted
// COMPONENT itself (name, center/onset, amplitude or net area ± σ first),
// with at%/wt% appended when the response happens to carry a quant block
// — the two exports intentionally overlap there rather than diverge on
// what a "net area" is. Pure string builders — no DOM, no store — so this
// is trivially unit-testable; the browser part reuses
// downloadCsv/csvBaseName from lib/eelsQuantCsv.ts, same as every other
// CSV export in the app.

import type {
  EdsPeakfitResult,
  EdsZetaQuant,
  EdsZetaResult,
  EelsFitResult,
} from "../api";

// ── numeric formatter — mirrors edsQuantCsv.ts / eelsQuantCsv.ts exactly,
//    so a fit report and a quant export never disagree on how a number
//    that appears in both renders. ────────────────────────────────────

function num(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "";
  return String(Number(v.toPrecision(7)));
}

export interface FitReportCsvContext {
  imageName: string;
}

/**
 * Serialise an EELS multi-edge model fit (`/eels/fit`) to a fit-report
 * CSV. Header carries the fit window actually optimised against
 * (`fit_range`, eV) and the fit-quality stats (χ²ᵣ, R²); one row per edge
 * with its onset, fitted amplitude ± 1σ, and the derived at% ± 1σ.
 */
export function eelsFitReportToCsv(
  r: EelsFitResult,
  ctx: FitReportCsvContext,
): string {
  const lines: string[] = [
    "# fermiviewer EELS fit report",
    `# image: ${ctx.imageName}`,
    `# fit_range_ev: ${num(r.fit_range[0])}-${num(r.fit_range[1])}`,
    `# reduced_chi2: ${num(r.reduced_chi2)}`,
    `# r_squared: ${num(r.r_squared)}`,
    `# converged: ${r.success}`,
    "element,shell,onset_ev,amplitude,amplitude_error," +
      "atomic_percent,atomic_percent_error",
  ];
  for (const e of r.edges) {
    lines.push(
      [
        e.element,
        e.shell,
        num(e.onset_ev),
        num(e.amplitude),
        num(e.amplitude_error),
        num(e.atomic_percent),
        num(e.atomic_percent_error),
      ].join(","),
    );
  }
  return lines.join("\n") + "\n";
}

function isZetaQuant(
  q: EdsPeakfitResult["quant"] | EdsZetaQuant,
): q is EdsZetaQuant {
  return q != null && "mass_thickness_kg_m2" in q;
}

/**
 * Serialise an EDS peak-deconvolution fit (`/eds/peakfit` or `/eds/zeta`)
 * to a fit-report CSV. Header carries the fit window (the full returned
 * energy axis — `fit_peaks` never windows, see routes/eds_advanced.py)
 * and the fit-quality stats; one row per element with its line energy,
 * net area ± 1σ (the fitted parameter), and at%/wt% ± 1σ when a quant
 * block is present. Works with or without `quantify` having been run.
 */
export function edsFitReportToCsv(
  r: EdsPeakfitResult | EdsZetaResult,
  ctx: FitReportCsvContext,
): string {
  const quant = r.quant;
  const zeta = isZetaQuant(quant) ? quant : null;
  const lo = r.energy.length > 0 ? r.energy[0] : Number.NaN;
  const hi = r.energy.length > 0 ? r.energy[r.energy.length - 1] : Number.NaN;
  const lines: string[] = [
    "# fermiviewer EDS fit report",
    `# image: ${ctx.imageName}`,
    `# method: ${zeta ? "zeta-factor" : quant ? "cliff-lorimer" : "none"}`,
    `# energy_range_kev: ${num(lo)}-${num(hi)}`,
    `# reduced_chi2: ${num(r.reduced_chi2)}`,
    `# r_squared: ${num(r.r_squared)}`,
    `# converged: ${r.success}`,
    "element,line,energy_kev,net_area,net_area_error," +
      "atomic_percent,atomic_percent_error,weight_percent,weight_percent_error",
  ];
  const qi = (sym: string) => quant?.elements.indexOf(sym) ?? -1;
  for (const el of r.elements) {
    const i = qi(el.symbol);
    lines.push(
      [
        el.symbol,
        el.line,
        num(el.energy_kev),
        num(el.net_area),
        num(el.net_area_error),
        num(i >= 0 ? quant?.atomic_percent[i] : null),
        num(i >= 0 ? quant?.atomic_percent_error?.[i] : null),
        num(i >= 0 ? quant?.weight_percent[i] : null),
        num(i >= 0 ? quant?.weight_percent_error?.[i] : null),
      ].join(","),
    );
  }
  return lines.join("\n") + "\n";
}
