// Pure helpers for components/analysis/PopulationHistogram.tsx: pdf
// evaluation for the three fitted distribution kinds, the honest
// count-scaling that makes the overlay curve comparable to the bar
// histogram, and the one-line population summary.
//
// The fitted-curve/histogram-overlay scaling is THE classic bug in this
// kind of chart (a raw pdf peaks at ~1/scale while a histogram peaks at
// up to N — plotting them unscaled on the same axes draws an invisible
// flat curve under a tall histogram, or a towering curve dwarfing the
// bars). y(x) = pdf(x) * N * binWidth is the correct scale: it is exactly
// the EXPECTED bar count of a bin of width binWidth centered at x, so
// integrating y(x) dx over the full range recovers N * binWidth (pinned
// in populationHistogram.test.ts).

import type {
  DistFit,
  DistributionHistogram,
  PopulationSummary,
} from "./api/distributions";
import type { ParticleRow } from "./api/imaging";
import { formatPlusMinus } from "./formatUncertainty";

const SQRT_2PI = Math.sqrt(2 * Math.PI);

/** Evaluate a fitted distribution's pdf at x, given its scipy-convention
 *  params (DistFit.params). Mirrors scipy.stats.{norm,lognorm,weibull_min}
 *  .pdf exactly for the parameterizations calc/distributions.py fits
 *  with (lognormal/weibull are always fit with loc pinned at 0, but this
 *  reads `loc` from params rather than assuming 0, so it stays correct
 *  if that ever changes). */
export function pdf(
  kind: DistFit["kind"],
  params: Record<string, number>,
  x: number,
): number {
  const loc = params.loc ?? 0;
  const scale = params.scale ?? 1;
  if (!(scale > 0)) return 0;
  switch (kind) {
    case "normal": {
      const z = (x - loc) / scale;
      return Math.exp(-0.5 * z * z) / (scale * SQRT_2PI);
    }
    case "lognormal": {
      const s = params.s ?? 1;
      const t = x - loc;
      if (!(t > 0) || !(s > 0)) return 0;
      const z = Math.log(t / scale) / s;
      return Math.exp(-0.5 * z * z) / (t * s * SQRT_2PI);
    }
    case "weibull": {
      const c = params.c ?? 1;
      const t = x - loc;
      if (t < 0 || !(c > 0)) return 0;
      if (t === 0) return c === 1 ? 1 / scale : 0;
      const r = t / scale;
      return (c / scale) * Math.pow(r, c - 1) * Math.exp(-Math.pow(r, c));
    }
    default:
      return 0;
  }
}

/** Sample the fitted pdf on an `nPoints`-point grid across [lo, hi] and
 *  scale each value to COUNTS: y(x) = pdf(x) * n * binWidth. */
export function scaledPdfCurve(
  fit: DistFit,
  lo: number,
  hi: number,
  n: number,
  binWidth: number,
  nPoints = 200,
): { x: number[]; y: number[] } {
  const x: number[] = new Array(nPoints);
  const y: number[] = new Array(nPoints);
  const step = nPoints > 1 ? (hi - lo) / (nPoints - 1) : 0;
  for (let i = 0; i < nPoints; i++) {
    const xi = lo + step * i;
    x[i] = xi;
    y[i] = pdf(fit.kind, fit.params, xi) * n * binWidth;
  }
  return { x, y };
}

/** Bin centers from a histogram's (n_bins + 1)-length edges array. */
export function binCenters(h: DistributionHistogram): number[] {
  const centers: number[] = new Array(h.counts.length);
  for (let i = 0; i < h.counts.length; i++) {
    centers[i] = (h.edges[i] + h.edges[i + 1]) / 2;
  }
  return centers;
}

/** Mean bin width across a histogram's edges (edges are uniform-width
 *  as produced by calc/distributions.histogram_bins, so this equals
 *  every individual bin's width; computed as a mean rather than
 *  `edges[1]-edges[0]` so it stays a sane approximation if that ever
 *  changes). Returns 0 for a histogram with no bins. */
export function meanBinWidth(h: DistributionHistogram): number {
  const n = h.counts.length;
  if (n === 0 || h.edges.length < 2) return 0;
  return (h.edges[h.edges.length - 1] - h.edges[0]) / n;
}

/** Choose calibrated values + `unit` when EVERY object has a calibrated
 *  size, else fall back to the px values with unit "px" — never a mix,
 *  and never a fake unit on an uncalibrated image. Used by both
 *  ParticlesMode and GrainsMode to feed PopulationHistogram from their
 *  respective per-object px/calibrated size arrays (particle
 *  equivalent diameter, grain equivalent diameter). */
export function pickSizeValues(
  pxValues: number[],
  calibratedValues: (number | null)[],
  unit: string,
): { values: number[]; unit: string } {
  const calibrated = calibratedValues.every((v) => v != null);
  if (calibrated && calibratedValues.length > 0) {
    return { values: calibratedValues as number[], unit };
  }
  return { values: pxValues, unit: "px" };
}

/** Population feed offered by ParticlesMode's metric picker
 *  (SHAPE_ANALYSIS_PLAN.md item 3): equivalent diameter and Feret max are
 *  lengths (calibrated-vs-px switching via `pickSizeValues`); circularity
 *  and aspect ratio are dimensionless (Convention 5 — no calibrated twin,
 *  no unit, never "px"). */
export type ParticleMetric =
  | "equiv_diameter"
  | "circularity"
  | "aspect_ratio"
  | "feret_max";

export const PARTICLE_METRIC_OPTIONS: { value: ParticleMetric; label: string }[] = [
  { value: "equiv_diameter", label: "Equivalent diameter" },
  { value: "circularity", label: "Circularity" },
  { value: "aspect_ratio", label: "Aspect ratio" },
  { value: "feret_max", label: "Feret max" },
];

export interface ParticleMetricPopulation {
  values: number[];
  /** "" for dimensionless metrics — show none, not "px". */
  unit: string;
  /** particles omitted from `values`. Currently only aspect ratio's
   *  `null` entries (degenerate minor axis) — never coerced to 0. */
  excluded: number;
}

/** Resolve one metric's population values + unit from a particle list,
 *  switching calibrated-vs-px exactly as `pickSizeValues` does for the
 *  two length metrics, and never inventing a unit for the two
 *  dimensionless ones. */
export function pickParticleMetricValues(
  particles: ParticleRow[],
  metric: ParticleMetric,
  unit: string,
): ParticleMetricPopulation {
  switch (metric) {
    case "equiv_diameter": {
      const picked = pickSizeValues(
        particles.map((p) => p.equiv_diameter),
        particles.map((p) => p.diameter_calibrated),
        unit,
      );
      return { ...picked, excluded: 0 };
    }
    case "feret_max": {
      const picked = pickSizeValues(
        particles.map((p) => p.feret_max),
        particles.map((p) => p.feret_max_calibrated),
        unit,
      );
      return { ...picked, excluded: 0 };
    }
    case "circularity":
      return {
        values: particles.map((p) => p.circularity),
        unit: "",
        excluded: 0,
      };
    case "aspect_ratio": {
      const withValue = particles.filter((p) => p.aspect_ratio != null);
      return {
        values: withValue.map((p) => p.aspect_ratio as number),
        unit: "",
        excluded: particles.length - withValue.length,
      };
    }
  }
}

/** One-line summary: "N=300 · mean 18.4 ± 3.2 nm · median 17.9 [15.1, 21.0] nm". */
export function formatPopulationSummary(
  s: PopulationSummary,
  unit: string,
): string {
  const meanPart = formatPlusMinus(s.mean, s.std);
  const u = unit ? ` ${unit}` : "";
  return (
    `N=${s.n}` +
    (s.n_dropped > 0 ? ` (${s.n_dropped} dropped)` : "") +
    ` · mean ${meanPart}${u}` +
    ` · median ${s.median.toFixed(2)} [${s.q1.toFixed(2)}, ${s.q3.toFixed(2)}]${u}`
  );
}
