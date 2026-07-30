// View-range math for the EDS spectrum's x (energy) axis.
//
// A view is `[lo, hi]` in the spectrum's own energy units, or `null` meaning
// "show everything". Collapsing a full-width view to null matters: it is what
// lets the plot fall back to uPlot's auto scale, so a Reset survives switching
// to a spectrum with a different energy range instead of pinning the new one
// to the old one's bounds.

export type XRange = [number, number];

/** Fit a candidate view inside the data bounds, honouring a minimum span so
 *  zooming can never collapse to a zero-width (undrawable) range. Returns null
 *  when the result covers the full data extent. */
export function clampRange(
  range: XRange,
  bounds: XRange,
  minSpan: number,
): XRange | null {
  const [dataLo, dataHi] = bounds;
  const full = dataHi - dataLo;
  if (!(full > 0)) return null;
  const [rawLo, rawHi] = range[0] <= range[1] ? range : [range[1], range[0]];
  const span = Math.min(
    full,
    Math.max(rawHi - rawLo, Math.min(Math.max(minSpan, 0), full)),
  );
  const center = (rawLo + rawHi) / 2;
  let lo = center - span / 2;
  if (lo < dataLo) lo = dataLo;
  if (lo + span > dataHi) lo = dataHi - span;
  const hi = lo + span;
  return span >= full - 1e-12 ? null : [lo, hi];
}

/** Zoom about a fixed energy — `factor` < 1 zooms in. Used by the wheel, where
 *  the energy under the cursor must stay under the cursor. */
export function zoomAbout(
  range: XRange | null,
  bounds: XRange,
  anchor: number,
  factor: number,
  minSpan: number,
): XRange | null {
  const [lo, hi] = range ?? bounds;
  return clampRange(
    [anchor - (anchor - lo) * factor, anchor + (hi - anchor) * factor],
    bounds,
    minSpan,
  );
}

/** Zoom about the view centre — the − / + buttons. */
export function zoomBy(
  range: XRange | null,
  bounds: XRange,
  factor: number,
  minSpan: number,
): XRange | null {
  const [lo, hi] = range ?? bounds;
  return zoomAbout(range, bounds, (lo + hi) / 2, factor, minSpan);
}

/** Shift the view by a fraction of its own width, clamped to the data. A
 *  full-width view has nowhere to pan, so it stays null. */
export function panBy(
  range: XRange | null,
  bounds: XRange,
  fraction: number,
  minSpan: number,
): XRange | null {
  if (!range) return null;
  const [lo, hi] = range;
  const shift = (hi - lo) * fraction;
  return clampRange([lo + shift, hi + shift], bounds, minSpan);
}

/** Centre the view on an energy window, leaving `pad` window-widths of
 *  context on each side — how clicking a pinned integration region frames it. */
export function frameWindow(
  eLo: number,
  eHi: number,
  bounds: XRange,
  minSpan: number,
  pad = 2.5,
): XRange | null {
  const width = Math.abs(eHi - eLo);
  const center = (eLo + eHi) / 2;
  const half = Math.max(width * (0.5 + pad), minSpan / 2);
  return clampRange([center - half, center + half], bounds, minSpan);
}
