// Energy-window integration of a displayed EDS spectrum.
//
// This is a deliberate port of the background models in
// src/fermiviewer/calc/eds_maps.py (`_side_windows`, `element_map`,
// `_kramers_bg_map`) so the number under the spectrum is the same quantity the
// element map integrates — just summed over the displayed spectrum's pixels
// instead of per pixel. Keeping it client-side means dragging the window
// updates the readout without a round trip, matching the explorer's existing
// "moving the window does not refetch a spectrum" contract.
//
// One intentional difference: the map clamps each pixel's net to ≥ 0, which a
// scalar readout must not do. A negative net is real information (the window
// holds no peak, or the background is over-subtracted) and hiding it behind a
// clamp would silently misreport an empty window as zero signal.

import type { Spectrum } from "../api";

export type EdsBackground = "none" | "linear" | "bremsstrahlung";

export interface WindowIntegration {
  eLo: number;
  eHi: number;
  bg: EdsBackground;
  /** Channels inside the peak window. */
  channels: number;
  /** Raw sum over the peak window. */
  gross: number;
  /** Background counts subtracted across the peak window. */
  background: number;
  /** gross − background, unclamped. */
  net: number;
  /** 1σ on `net` from counting statistics, including background propagation. */
  sigma: number;
  /** Sum over the whole displayed spectrum. */
  total: number;
  /** net / total, or 0 when the spectrum is empty. */
  fraction: number;
  /** Set when the requested background could not be applied as asked. */
  note?: string;
}

interface Side {
  sum: number;
  count: number;
}

/** Background counts over the peak window, its variance, and why it is zero
 *  when it could not be estimated. */
interface BackgroundEstimate {
  bg: number;
  variance: number;
  note?: string;
}

const NO_FLANKS: BackgroundEstimate = {
  bg: 0,
  variance: 0,
  note: "no flanking channels — background skipped",
};

/** Indices of the two flanking background windows — the port of
 *  `_side_windows`: each side is one peak-width wide, `gap` keV clear of the
 *  peak edge, and half-open on the side that touches the peak. */
function sideWindows(
  energy: readonly number[],
  eLo: number,
  eHi: number,
  bgWidth: number,
  bgGap: number,
): { lo: number[]; hi: number[] } {
  const width = bgWidth > 0 ? bgWidth : eHi - eLo;
  const gap = Math.max(bgGap, 0);
  const lo: number[] = [];
  const hi: number[] = [];
  for (let i = 0; i < energy.length; i++) {
    const e = energy[i];
    if (e >= eLo - gap - width && e < eLo - gap) lo.push(i);
    else if (e > eHi + gap && e <= eHi + gap + width) hi.push(i);
  }
  return { lo, hi };
}

function accumulate(counts: readonly number[], indices: number[]): Side {
  let sum = 0;
  for (const i of indices) sum += counts[i] ?? 0;
  return { sum, count: indices.length };
}

/** Flat-rate background from one flank: rate × peak channels, with the
 *  Poisson variance of that scaled estimate. */
function flatSide(
  side: Side,
  nPeak: number,
  weight: number,
): BackgroundEstimate {
  const scale = (weight * nPeak) / side.count;
  return {
    bg: scale * side.sum,
    variance: scale * scale * Math.max(side.sum, 0),
  };
}

function linearBackground(
  counts: readonly number[],
  lo: number[],
  hi: number[],
  nPeak: number,
): BackgroundEstimate {
  const left = accumulate(counts, lo);
  const right = accumulate(counts, hi);
  if (left.count > 0 && right.count > 0) {
    const a = flatSide(left, nPeak, 0.5);
    const b = flatSide(right, nPeak, 0.5);
    return { bg: a.bg + b.bg, variance: a.variance + b.variance };
  }
  if (left.count > 0) return flatSide(left, nPeak, 1);
  if (right.count > 0) return flatSide(right, nPeak, 1);
  return NO_FLANKS;
}

/** Kramers continuum with only its amplitude fitted to the flanking channels,
 *  the 1-D form of `_kramers_bg_map`. */
function kramersBackground(
  energy: readonly number[],
  counts: readonly number[],
  peak: number[],
  lo: number[],
  hi: number[],
  e0Kev: number,
): BackgroundEstimate {
  if (!Number.isFinite(e0Kev) || e0Kev <= energy[peak[peak.length - 1]]) {
    return {
      bg: 0,
      variance: 0,
      note: "beam energy must exceed the window — background skipped",
    };
  }
  const shape = (i: number) => {
    const e = energy[i];
    return e < e0Kev ? Math.max(e0Kev - e, 0) / Math.max(e, 1e-9) : 0;
  };
  const side = [...lo, ...hi];
  let denom = 0;
  let numerator = 0;
  let ampVariance = 0;
  for (const i of side) {
    const c = shape(i);
    denom += c * c;
    numerator += c * (counts[i] ?? 0);
    ampVariance += c * c * Math.max(counts[i] ?? 0, 0);
  }
  if (denom <= 0) return NO_FLANKS;
  const amp = numerator / denom;
  let peakShape = 0;
  for (const i of peak) peakShape += shape(i);
  return {
    bg: amp * peakShape,
    variance: ((peakShape * peakShape) / (denom * denom)) * ampVariance,
  };
}

/**
 * Integrate `[eLo, eHi]` of a spectrum under the requested background model.
 * Returns null when the window contains no channels, so callers can render
 * "no channels in window" rather than a misleading zero.
 */
export function integrateWindow(
  spec: Spectrum,
  eLo: number,
  eHi: number,
  bg: EdsBackground = "linear",
  opts: { e0Kev?: number; bgWidth?: number; bgGap?: number } = {},
): WindowIntegration | null {
  const [lowEdge, highEdge] = eHi < eLo ? [eHi, eLo] : [eLo, eHi];
  const energy = spec.energy;
  const counts = spec.counts;
  const peak: number[] = [];
  let total = 0;
  for (let i = 0; i < energy.length; i++) {
    total += counts[i] ?? 0;
    if (energy[i] >= lowEdge && energy[i] <= highEdge) peak.push(i);
  }
  if (peak.length === 0) return null;

  const gross = accumulate(counts, peak).sum;
  const { lo, hi } = sideWindows(
    energy,
    lowEdge,
    highEdge,
    opts.bgWidth ?? 0,
    opts.bgGap ?? 0,
  );
  const estimate: BackgroundEstimate =
    bg === "linear"
      ? linearBackground(counts, lo, hi, peak.length)
      : bg === "bremsstrahlung"
        ? kramersBackground(energy, counts, peak, lo, hi, opts.e0Kev ?? NaN)
        : { bg: 0, variance: 0 };

  return {
    eLo: lowEdge,
    eHi: highEdge,
    bg,
    channels: peak.length,
    gross,
    background: estimate.bg,
    net: gross - estimate.bg,
    sigma: Math.sqrt(Math.max(gross, 0) + estimate.variance),
    total,
    fraction: total > 0 ? (gross - estimate.bg) / total : 0,
    note: estimate.note,
  };
}
