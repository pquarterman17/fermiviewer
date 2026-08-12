// Population histogram + distribution fitting (ANALYSIS_PRESENTATION_PLAN.md
// #6, audit R6). Mirrors routes/distributions.py's POST /api/analyze/distribution
// — stateless: the caller already holds the per-object metric values from a
// particles/grains analysis response and posts that plain list here.

import { post } from "./transport";

export interface PopulationSummary {
  n: number;
  n_dropped: number;
  mean: number;
  std: number;
  min: number;
  max: number;
  median: number;
  q1: number;
  q3: number;
}

export interface DistributionHistogram {
  /** n_bins + 1 bin edges. */
  edges: number[];
  /** n_bins counts. */
  counts: number[];
}

export type DistributionKind = "normal" | "lognormal" | "weibull";

export interface DistFit {
  kind: DistributionKind;
  /** scipy parameter names — {loc, scale} for normal, {s, loc, scale} for
   *  lognormal, {c, loc, scale} for weibull. */
  params: Record<string, number>;
  log_likelihood: number;
  aic: number;
  ks_statistic: number;
  ks_pvalue: number;
}

export interface DistributionFits {
  normal: DistFit | null;
  lognormal: DistFit | null;
  weibull: DistFit | null;
  /** AIC-selected winner; null when only a single kind was fit. */
  best: DistributionKind | null;
}

export interface DistributionResult {
  summary: PopulationSummary;
  histogram: DistributionHistogram;
  fits: DistributionFits | null;
}

/** Summary + histogram + distribution fit(s) over a raw value list.
 *  `fit` defaults to "all" (fetch every fit once; a UI selector should
 *  switch which curve it draws client-side rather than re-requesting). */
export function analyzeDistribution(
  values: number[],
  fit: DistributionKind | "all" | "none" = "all",
): Promise<DistributionResult> {
  return post("/api/analyze/distribution", { values, fit });
}
