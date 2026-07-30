import { buildLut, type ColormapName } from "./colormaps";

export interface MapDisplayRange {
  dataMin: number;
  dataMax: number;
  lo: number;
  hi: number;
}

function percentile(sorted: number[], pct: number): number {
  if (sorted.length === 0) return 0;
  const position = ((sorted.length - 1) * pct) / 100;
  const lower = Math.floor(position);
  const fraction = position - lower;
  return (
    sorted[lower] +
    (sorted[Math.min(lower + 1, sorted.length - 1)] - sorted[lower]) * fraction
  );
}

/** Finite-value statistics and percentile window for an EDS element map. */
export function mapDisplayRange(
  map: number[][],
  lowPercentile: number,
  highPercentile: number,
): MapDisplayRange {
  const values = map
    .flat()
    .filter(Number.isFinite)
    .sort((a, b) => a - b);
  if (values.length === 0) {
    return { dataMin: 0, dataMax: 0, lo: 0, hi: 1 };
  }
  const dataMin = values[0];
  const dataMax = values[values.length - 1];
  const lo = percentile(values, Math.max(0, Math.min(100, lowPercentile)));
  const rawHi = percentile(values, Math.max(0, Math.min(100, highPercentile)));
  return { dataMin, dataMax, lo, hi: rawHi > lo ? rawHi : lo + 1 };
}

/** Convert a numeric map to an RGBA raster. `cmap` is a shared application
 *  colormap name, or a prebuilt 256×RGBA8 LUT for ramps that are generated per
 *  render — the per-element colour tint being the one that needs it. */
export function renderElementMap(
  map: number[][],
  width: number,
  height: number,
  range: MapDisplayRange,
  cmap: ColormapName | Uint8Array,
): Uint8ClampedArray {
  const rgba = new Uint8ClampedArray(width * height * 4);
  const lut = cmap instanceof Uint8Array ? cmap : buildLut(cmap);
  const span = range.hi - range.lo || 1;
  for (let i = 0; i < width * height; i++) {
    const value = map[Math.floor(i / width)]?.[i % width];
    const normalized = Number.isFinite(value)
      ? Math.max(0, Math.min(1, (value - range.lo) / span))
      : 0;
    const lutOffset = Math.round(normalized * 255) * 4;
    rgba[i * 4] = lut[lutOffset];
    rgba[i * 4 + 1] = lut[lutOffset + 1];
    rgba[i * 4 + 2] = lut[lutOffset + 2];
    rgba[i * 4 + 3] = 255;
  }
  return rgba;
}

export function formatMapValue(value: number): string {
  const magnitude = Math.abs(value);
  if (magnitude !== 0 && (magnitude < 0.01 || magnitude >= 100_000)) {
    return value.toExponential(2);
  }
  return Number(value.toPrecision(4)).toString();
}
