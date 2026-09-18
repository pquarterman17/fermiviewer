// Measuring a span of a 1-D profile: what two points you drop on it mean,
// and what data an edge fit should be given.
//
// Pure decisions only — no DOM, no fetch — so the arithmetic that decides
// "which samples are you fitting" is testable without a plot.
//
// **Why a span and not two clicks.** The two things a user wants from a
// profile are the distance between two features and the width of the edge
// between them, and both come from the same gesture: drag across the
// transition. Asking for a click pair for one and a bracket for the other
// would make them feel like unrelated tools when they are two readings of
// one selection.

export interface ProfileSpan {
  /** calibrated x at each end, ordered low to high */
  x0: number;
  x1: number;
  /** |x1 - x0| — the distance measurement */
  length: number;
  /** the samples inside the span, for fitting */
  x: number[];
  y: number[];
  /** intensity at each end, read from the nearest sample */
  y0: number;
  y1: number;
  /** y1 - y0: the step across the span */
  step: number;
}

/**
 * `null` when the span holds fewer than 4 samples — `fit_interface_width`
 * refuses below that, and returning a span the fit will reject only moves
 * the error somewhere less obvious.
 */
export function profileSpan(
  dist: number[],
  intensity: (number | null)[],
  a: number,
  b: number,
  minSamples = 4,
): ProfileSpan | null {
  const x0 = Math.min(a, b);
  const x1 = Math.max(a, b);
  const x: number[] = [];
  const y: number[] = [];
  for (let i = 0; i < dist.length; i++) {
    const v = intensity[i];
    // a non-finite sample is a gap where the profile ran off the raster,
    // not a zero; dropping it keeps the fit from being pulled to a value
    // that was never measured
    if (dist[i] < x0 || dist[i] > x1 || v == null || !Number.isFinite(v)) continue;
    x.push(dist[i]);
    y.push(v);
  }
  if (x.length < minSamples) return null;
  return {
    x0,
    x1,
    length: x1 - x0,
    x,
    y,
    y0: y[0],
    y1: y[y.length - 1],
    step: y[y.length - 1] - y[0],
  };
}

/** Format a value with its 1σ, or the value alone when there is no σ. */
export function withSigma(
  value: number,
  sigma: number | null | undefined,
  unit: string,
  digits = 3,
): string {
  const v = Number(value.toPrecision(digits));
  // "±0" would claim exactness; an absent sigma is shown as absent
  if (sigma == null || !Number.isFinite(sigma)) return `${v} ${unit}`;
  return `${v} ± ${Number(sigma.toPrecision(2))} ${unit}`;
}
