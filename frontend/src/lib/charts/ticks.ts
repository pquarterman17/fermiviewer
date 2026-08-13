// "Nice" tick-position helpers for the chart SVG exporter (chartSvg.ts).
//
// uPlot computes its own on-screen ticks internally using undocumented,
// version-specific heuristics that are not part of its public API. Rather
// than reach into those, the exporter recomputes a standard 1-2-5 ladder
// from the PUBLIC min/max range alone — the same classic axis-labelling
// algorithm every plotting tool converges on (D3's d3.ticks, matplotlib's
// MaxNLocator, Excel/Origin's default axis ticks). It will not byte-for-byte
// match whatever uPlot drew on screen, but it produces the same *kind* of
// ladder a reader expects from a publication figure.

export interface TickLadderOptions {
  /** Roughly how many ticks to aim for; the ladder snaps to a clean step so
   *  the actual count varies a bit either side of this. */
  targetCount?: number;
}

const NICE_STEPS = [1, 2, 5, 10];

/** Round a rough per-tick step up to the nearest 1/2/5×10ⁿ. */
function niceStep(roughStep: number): number {
  if (!Number.isFinite(roughStep) || roughStep <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(roughStep));
  const residual = roughStep / magnitude;
  const chosen = NICE_STEPS.find((s) => residual <= s) ?? 10;
  return chosen * magnitude;
}

/** Decimal places to round a ladder's values to, so float noise (0.1 + 0.2
 *  style artifacts) never leaks into a tick label. */
function roundingDecimals(step: number): number {
  if (!Number.isFinite(step) || step <= 0) return 0;
  return Math.min(12, Math.max(0, -Math.floor(Math.log10(step)) + 6));
}

/**
 * Linear 1-2-5 tick ladder covering [min, max] (order-independent). A
 * degenerate range (min === max, including both zero) is padded to a small
 * symmetric span first so callers always get a usable ladder rather than an
 * empty one.
 */
export function niceTicks(
  min: number,
  max: number,
  opts: TickLadderOptions = {},
): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [];
  const targetCount = Math.max(1, opts.targetCount ?? 5);
  let lo = Math.min(min, max);
  let hi = Math.max(min, max);
  if (lo === hi) {
    const pad = lo === 0 ? 1 : Math.abs(lo) * 0.1;
    lo -= pad;
    hi += pad;
  }
  const step = niceStep((hi - lo) / targetCount);
  const niceMin = Math.floor(lo / step) * step;
  const niceMax = Math.ceil(hi / step) * step;
  const decimals = roundingDecimals(step);
  const ticks: number[] = [];
  for (let v = niceMin; v <= niceMax + step / 2; v += step) {
    ticks.push(Number(v.toFixed(decimals)));
  }
  return ticks;
}

/**
 * Log-scale tick ladder: 1/2/5 × 10^k within [min, max]. Both bounds must be
 * strictly positive — chartSvg.ts never plots non-positive values on a log
 * axis (they are treated as gaps), so by the time a domain reaches this
 * helper its bounds already exclude them.
 */
export function niceLogTicks(min: number, max: number): number[] {
  if (
    !Number.isFinite(min) ||
    !Number.isFinite(max) ||
    min <= 0 ||
    max <= 0
  ) {
    return [];
  }
  const lo = Math.min(min, max);
  const hi = Math.max(min, max);
  const startExp = Math.floor(Math.log10(lo));
  const endExp = Math.ceil(Math.log10(hi));
  const ticks: number[] = [];
  for (let e = startExp; e <= endExp; e++) {
    for (const m of [1, 2, 5]) {
      const v = m * 10 ** e;
      // a hair of slack so an endpoint that lands exactly on a decade isn't
      // dropped by float rounding in the log10/pow round trip
      if (v >= lo * 0.9999 && v <= hi * 1.0001) ticks.push(v);
    }
  }
  return ticks;
}

/**
 * Trailing-zero-free numeric tick label, matching uPlot's own default
 * formatter style: no unnecessary decimals, and no scientific notation
 * except where JS's own Number#toString already switches to it (extreme
 * magnitudes, same as uPlot's own axis labels do).
 */
export function formatTickLabel(value: number): string {
  if (!Number.isFinite(value)) return "";
  if (value === 0) return "0";
  // Number#toPrecision(10) then re-parsing kills float representation noise
  // (e.g. 0.30000000000000004) without imposing a fixed decimal count.
  return Number(value.toPrecision(10)).toString();
}
