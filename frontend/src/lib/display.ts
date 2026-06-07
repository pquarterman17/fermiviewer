// Display-pipeline helpers shared by the Adjust panel and keyboard
// shortcuts. Mirrors calc/render.py semantics client-side.

import type { Raster16 } from "./api";

/** Percentile-based auto-contrast window over the raw raster.
 *  Returns normalized [0,1] lo/hi (the shader's window space). */
export function autoWindow(
  r: Raster16,
  pLo = 0.5,
  pHi = 99.5,
): { lo: number; hi: number } {
  // exact percentiles via a 65536-bin histogram — O(n), no sort
  const counts = new Uint32Array(65536);
  for (let i = 0; i < r.data.length; i++) counts[r.data[i]]++;
  const n = r.data.length;
  const target = (p: number) => (p / 100) * n;
  let acc = 0;
  let lo = 0;
  let hi = 65535;
  let loDone = false;
  const tLo = target(pLo);
  const tHi = target(pHi);
  for (let v = 0; v < 65536; v++) {
    acc += counts[v];
    if (!loDone && acc >= tLo) {
      lo = v;
      loDone = true;
    }
    if (acc >= tHi) {
      hi = v;
      break;
    }
  }
  if (hi <= lo) hi = Math.min(65535, lo + 1);
  return { lo: lo / 65535, hi: hi / 65535 };
}

/** Map a normalized [0,1] window value to real intensity units. */
export function toReal(norm: number, r: Raster16): number {
  return norm * (r.vmax - r.vmin) + r.vmin;
}

/** Map a real intensity to the normalized [0,1] window space. */
export function toNorm(real: number, r: Raster16): number {
  const span = r.vmax - r.vmin || 1;
  return Math.min(1, Math.max(0, (real - r.vmin) / span));
}
