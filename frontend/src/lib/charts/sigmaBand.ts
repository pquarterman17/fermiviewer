// Reusable ±1σ shaded-band helper for uPlot charts (ANALYSIS_PRESENTATION_PLAN
// item 3). uPlot has no "error band" primitive of its own — its native way to
// shade a region is `bands`, which fills the area between two ALREADY-PLOTTED
// series (see uplot's own demos/high-low-bands.html: a "High" and a "Low"
// line, plus `bands: [{ series: [hiIdx, loIdx] }]`). This module builds that
// hi/lo series pair, the matching data rows, and the `bands` entry for ONE
// line's ±σ shading — the composition-profile chart is the first caller;
// later item-3 charts (residual/fit-parameter bands) reuse `sigmaBand()`.
//
// A band's fill only draws when BOTH its edge series are `show: true` (uPlot
// gates the fill on `lowerEdge.show`), so the hi/lo boundary series must be
// real, visible-to-uPlot series — they cannot simply be omitted or `show:
// false`. They carry no information of their own though, so they are marked
// with `BAND_LEGEND_ROW_CLASS` for the caller's stylesheet to hide
// (`.fvd-ws-plot tr.fvd-band-row { display: none }` in
// styles/theme-web/07-preferences-workshops.css) rather than uPlot's own
// on/off legend styling. Hiding the row this way also removes it from
// pointer-event hit testing, so it cannot capture a legend click — and
// because the hi/lo series are always appended AFTER the caller's own line
// series, adding a band never renumbers an existing line series' index.

import type uPlot from "uplot";

/** CSS class a hi/lo band-boundary series' legend row carries, so a
 *  stylesheet can hide it without touching uPlot's own `u-off` class. */
export const BAND_LEGEND_ROW_CLASS = "fvd-band-row";

/**
 * y±σ bounds, pointwise. A point maps to `null` (uPlot's own gap value —
 * never `NaN`, which would poison `Math.min`/`Math.max` scale autoranging
 * for the WHOLE axis, not just that point) whenever its y is missing/
 * non-finite or its σ is missing, non-finite, or negative. That point then
 * draws no band, matching how a bare uPlot line already gaps on `null` y.
 */
export function sigmaBounds(
  y: readonly (number | null | undefined)[],
  sigma: readonly (number | null | undefined)[],
): { hi: (number | null)[]; lo: (number | null)[] } {
  if (y.length !== sigma.length) {
    throw new Error("y and sigma must be the same length");
  }
  const hi: (number | null)[] = new Array(y.length);
  const lo: (number | null)[] = new Array(y.length);
  for (let i = 0; i < y.length; i++) {
    const yi = y[i];
    const si = sigma[i];
    const valid =
      yi != null && Number.isFinite(yi) &&
      si != null && Number.isFinite(si) && si >= 0;
    if (valid) {
      hi[i] = yi + si;
      lo[i] = yi - si;
    } else {
      hi[i] = null;
      lo[i] = null;
    }
  }
  return { hi, lo };
}

/**
 * #rrggbb + alpha → an `rgba()` CSS colour string, for a band's fill.
 * Element colours (`useElementColors`) are always validated 6-digit hex, so
 * no other input shape is handled; an unparseable input falls back to a
 * neutral grey rather than throwing (a chart should still render).
 */
export function hexToRgba(hex: string, alpha: number): string {
  const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
  const [r, g, b] = m
    ? [m[1], m[2], m[3]].map((h) => parseInt(h, 16))
    : [136, 136, 136];
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

export interface SigmaBandConfig {
  /** hi/lo Series to append to the plot's `series[]`, in this order. */
  series: [uPlot.Series, uPlot.Series];
  /** hi/lo data rows to append to the aligned data array, matching `series`. */
  data: [(number | null)[], (number | null)[]];
  /**
   * The `bands[]` entry. `hiIndex`/`loIndex` are the ABSOLUTE indices the
   * caller is about to place the two `series` above at, within the plot's
   * full `series[]` (x is always index 0) — `sigmaBand` only records them
   * into this entry, it never touches any other series' position, so
   * appending several bands after N line series never renumbers them.
   */
  band: uPlot.Band;
}

/**
 * Build the hi/lo series + data + band for one line's ±σ shading.
 *
 * `y`/`sigma` are that ONE series' own values (not the whole chart's data).
 * `hiIndex`/`loIndex` must be the positions the caller is about to place the
 * returned `series` pair at in the plot's full series array.
 */
export function sigmaBand(
  y: readonly (number | null | undefined)[],
  sigma: readonly (number | null | undefined)[],
  color: string,
  hiIndex: number,
  loIndex: number,
  opts: { fillAlpha?: number; label?: string } = {},
): SigmaBandConfig {
  const { hi, lo } = sigmaBounds(y, sigma);
  const fill = hexToRgba(color, opts.fillAlpha ?? 0.18);
  const label = opts.label ?? "±1σ";
  const boundSeries: uPlot.Series = {
    show: true,
    class: BAND_LEGEND_ROW_CLASS,
    label,
    stroke: color,
    width: 0,
    points: { show: false },
  };
  return {
    series: [{ ...boundSeries }, { ...boundSeries }],
    data: [hi, lo],
    band: { series: [hiIndex, loIndex], fill, dir: -1 },
  };
}
