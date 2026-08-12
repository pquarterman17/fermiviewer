// Edge-window integration of a displayed EELS spectrum.
//
// This is a deliberate port of the pre-edge background model in
// src/fermiviewer/calc/eels.py (`background`, `extract_map`) so the number
// under the spectrum is the same quantity the elemental map integrates — just
// summed over the displayed spectrum instead of per pixel. Keeping it
// client-side means dragging a window updates the readout without a round
// trip, matching lib/eds/integrate.ts's contract for the EDS window.
//
// Two intentional differences from the map path, both shared with the EDS
// readout and for the same reasons:
//   - the map clamps each pixel's residual to ≥ 0; a scalar readout must not.
//     A negative net is real information (no edge in the window, or the fit
//     overshoots) and clamping would misreport it as zero signal.
//   - the backend RAISES when the fit window has < 2 channels; a readout
//     degrades to a direct sum with a note instead, because mid-drag windows
//     pass through every bad state on the way to a good one.

import type { Spectrum } from "../api";
import { orderWindow, type EnergyWindow } from "../spectrum/species";

export type EelsBackgroundMethod = "powerlaw" | "exponential";

export interface EdgeIntegration {
  signal: EnergyWindow;
  background?: EnergyWindow;
  method: EelsBackgroundMethod;
  /** Channels inside the signal window. */
  channels: number;
  /** Raw sum over the signal window. */
  gross: number;
  /** Fitted background counts extrapolated across the signal window. */
  background_counts: number;
  /** gross − background_counts, unclamped. */
  net: number;
  /** 1σ on `net`: counting statistics plus the fit's extrapolation variance. */
  sigma: number;
  /** Fitted parameters — powerlaw {A, r} (I = A·E^−r), exponential {A, b}. */
  params?: Record<string, number>;
  /** Set when the requested background could not be fitted as asked. */
  note?: string;
}

const EPS = Number.MIN_VALUE;

/** ln of a count/energy, floored the way the backend floors with `_EPS`. */
function safeLog(v: number): number {
  return Math.log(Math.max(v, EPS));
}

function channelsIn(energy: readonly number[], w: EnergyWindow): number[] {
  const idx: number[] = [];
  for (let i = 0; i < energy.length; i++) {
    if (energy[i] >= w.lo && energy[i] <= w.hi) idx.push(i);
  }
  return idx;
}

/** Unweighted least squares y = m·x + c (what `np.polyfit(x, y, 1)` does),
 *  plus the delta-method covariance of (m, c) under per-point variances
 *  var(y_k) — the sandwich (XᵀX)⁻¹ XᵀVX (XᵀX)⁻¹, which is what makes the
 *  readout's σ honest about how far the fit is extrapolated. */
function fitLine(
  x: readonly number[],
  y: readonly number[],
  yVar: readonly number[],
): { m: number; c: number; cov: [number, number, number] } | null {
  const n = x.length;
  let sx = 0;
  let sxx = 0;
  let sy = 0;
  let sxy = 0;
  for (let k = 0; k < n; k++) {
    sx += x[k];
    sxx += x[k] * x[k];
    sy += y[k];
    sxy += x[k] * y[k];
  }
  const det = n * sxx - sx * sx;
  if (!(det > 0)) return null; // all fit channels at one energy
  const m = (n * sxy - sx * sy) / det;
  const c = (sxx * sy - sx * sxy) / det;
  // Rows of (XᵀX)⁻¹Xᵀ give each point's weight in (m, c); accumulate VarΣ.
  let vmm = 0;
  let vcc = 0;
  let vmc = 0;
  for (let k = 0; k < n; k++) {
    const wm = (n * x[k] - sx) / det;
    const wc = (sxx - sx * x[k]) / det;
    vmm += wm * wm * yVar[k];
    vcc += wc * wc * yVar[k];
    vmc += wm * wc * yVar[k];
  }
  return { m, c, cov: [vmm, vcc, vmc] };
}

/**
 * Integrate an EELS signal window with an optional pre-edge background fit.
 *
 * Without `backgroundWindow` the signal window is summed directly (the
 * backend's `background_window is None` path). Returns null when the signal
 * window contains no channels, so callers can render "no channels in window"
 * rather than a misleading zero.
 */
export function integrateEdge(
  spec: Spectrum,
  signalWindow: EnergyWindow,
  backgroundWindow?: EnergyWindow,
  method: EelsBackgroundMethod = "powerlaw",
): EdgeIntegration | null {
  const signal = orderWindow(signalWindow);
  const energy = spec.energy;
  const counts = spec.counts;
  const sig = channelsIn(energy, signal);
  if (sig.length === 0) return null;

  let gross = 0;
  for (const i of sig) gross += counts[i] ?? 0;

  const base: EdgeIntegration = {
    signal,
    method,
    channels: sig.length,
    gross,
    background_counts: 0,
    net: gross,
    sigma: Math.sqrt(Math.max(gross, 0)),
  };
  if (!backgroundWindow) {
    return { ...base, note: "no background window — direct sum" };
  }

  const background = orderWindow(backgroundWindow);
  const fit = channelsIn(energy, background);
  if (fit.length < 2) {
    return {
      ...base,
      background,
      note: "background window has < 2 channels — background skipped",
    };
  }

  // Fit ln(I) against ln(E) (powerlaw) or E (exponential), exactly the
  // backend's polyfit; var(ln I) ≈ 1/I by the Poisson delta method.
  const xs: number[] = [];
  const ys: number[] = [];
  const yVar: number[] = [];
  for (const k of fit) {
    xs.push(method === "powerlaw" ? safeLog(energy[k]) : energy[k]);
    ys.push(safeLog(counts[k] ?? 0));
    yVar.push(1 / Math.max(counts[k] ?? 0, 1));
  }
  const line = fitLine(xs, ys, yVar);
  if (!line) {
    return {
      ...base,
      background,
      note: "background channels share one energy — background skipped",
    };
  }

  // Extrapolate under the signal window and total it, tracking the gradient
  // of that total w.r.t. (m, c) for the variance.
  let bgTotal = 0;
  let gm = 0; // ∂(Σbg)/∂m = Σ bg_i·x_i
  let gc = 0; // ∂(Σbg)/∂c = Σ bg_i
  for (const i of sig) {
    const xi = method === "powerlaw" ? safeLog(energy[i]) : energy[i];
    const bg = Math.exp(line.c + line.m * xi);
    if (!Number.isFinite(bg)) continue; // noisy fit overflow → clamp, like the map
    bgTotal += bg;
    gm += bg * xi;
    gc += bg;
  }
  const [vmm, vcc, vmc] = line.cov;
  const bgVariance = gm * gm * vmm + gc * gc * vcc + 2 * gm * gc * vmc;

  const params: Record<string, number> =
    method === "powerlaw"
      ? { A: Math.exp(line.c), r: -line.m }
      : { A: Math.exp(line.c), b: line.m };

  return {
    ...base,
    background,
    background_counts: bgTotal,
    net: gross - bgTotal,
    sigma: Math.sqrt(Math.max(gross, 0) + Math.max(bgVariance, 0)),
    params,
  };
}
