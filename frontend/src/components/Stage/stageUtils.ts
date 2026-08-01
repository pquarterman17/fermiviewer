// Pure module-level helpers for Stage.tsx, split out in the repo-health
// #33 decomposition. Moved verbatim; no behavior changes.

export interface Pt {
  x: number;
  y: number;
}

export const WHEEL_K = 0.0015;
/** Apply a display intensity transform to a normalized-u16 raster
 *  (log: log1p rescale; equalize: 4096-bin CDF mapping). */
export function transformU16(
  data: Uint16Array,
  mode: "linear" | "log" | "equalize",
): Uint16Array {
  if (mode === "linear") return data;
  const out = new Uint16Array(data.length);
  if (mode === "log") {
    const k = 65535 / Math.log1p(65535);
    for (let i = 0; i < data.length; i++) {
      out[i] = Math.round(Math.log1p(data[i]) * k);
    }
    return out;
  }
  // equalize: histogram → CDF → remap
  const BINS = 4096;
  const hist = new Float64Array(BINS);
  for (let i = 0; i < data.length; i++) hist[data[i] >> 4]++;
  const cdf = new Float64Array(BINS);
  let acc = 0;
  for (let b = 0; b < BINS; b++) {
    acc += hist[b];
    cdf[b] = acc;
  }
  const lo = cdf.find((v) => v > 0) ?? 0;
  const span = acc - lo || 1;
  const lut = new Uint16Array(BINS);
  for (let b = 0; b < BINS; b++) {
    lut[b] = Math.round(((cdf[b] - lo) / span) * 65535);
  }
  for (let i = 0; i < data.length; i++) out[i] = lut[data[i] >> 4];
  return out;
}

export const CLICKS: Record<string, number> = {
  distance: 2,
  profile: 2,
  angle: 3,
  polyline: Infinity, // vertices accumulate; double-click finishes
  text: 1,
  arrow: 2,
  box: 2,
  circle: 2,
  calibrate: 2, // two-click line (snaps H/V) used to set the pixel size
};

/** Snap point b to a horizontal/vertical line through a (whichever axis the
 *  drag favours); `free` (Shift held) returns b unchanged. Used by the
 *  calibration line so a flat baked scale bar is easy to trace precisely. */
export function snapHV(a: Pt, b: Pt, free: boolean): Pt {
  if (free) return b;
  return Math.abs(b.x - a.x) >= Math.abs(b.y - a.y)
    ? { x: b.x, y: a.y }
    : { x: a.x, y: b.y };
}
