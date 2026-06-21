// Pure multi-channel composite blend (Quick-Wins #6), extracted from
// EdsComposite so it can be unit-tested without a canvas. Each channel maps
// its 16-bit raster through a per-channel colour ramp (a flat black→colour
// "solid" tint by default, or any named colormap LUT), with an optional
// per-channel contrast window, then the channels are added and clamped.
//
// "solid" with the default 0..1 window is byte-identical to the original
// flat-colour additive blend, so existing composites are unchanged.

import { buildLut, type ColormapName } from "./colormaps";

export interface CompositeChannel {
  color: string; // hex, used by the "solid" ramp (black → colour)
  intensity: number; // gain, 0–2
  visible: boolean;
  /** per-channel ramp: undefined/"solid" → flat colour; else a named LUT */
  cmap?: string;
  /** per-channel contrast window over the normalized 0..1 raster value */
  lo?: number;
  hi?: number;
}

export interface CompositeRaster {
  w: number;
  h: number;
  data: Uint16Array | Int32Array | number[];
}

function hexToRgb(hex: string): [number, number, number] {
  const c = hex.replace("#", "");
  return [
    parseInt(c.slice(0, 2), 16) || 0,
    parseInt(c.slice(2, 4), 16) || 0,
    parseInt(c.slice(4, 6), 16) || 0,
  ];
}

const NAMED_CMAP = (cmap?: string): cmap is ColormapName =>
  !!cmap && cmap !== "solid";

/** Blend N equal-size 16-bit rasters into an RGBA8 buffer. `rasters[k]`
 *  pairs with `channels[k]`. Returns the pixel buffer + dims; the caller
 *  wraps it in ImageData (kept out of here so the math is canvas-free). */
export function compositeChannels(
  rasters: CompositeRaster[],
  channels: CompositeChannel[],
): { w: number; h: number; rgba: Uint8ClampedArray } {
  const { w, h } = rasters[0];
  const n = w * h;
  const acc = new Float32Array(n * 3);

  channels.forEach((c, k) => {
    if (!c.visible || !rasters[k]) return;
    const { data } = rasters[k];
    const lo = c.lo ?? 0;
    const hi = c.hi ?? 1;
    const span = hi > lo ? hi - lo : 1;
    const lut = NAMED_CMAP(c.cmap) ? buildLut(c.cmap) : null;
    const [r, g, b] = hexToRgb(c.color);
    const gain = c.intensity;

    for (let i = 0; i < n; i++) {
      let t = (data[i] / 65535 - lo) / span; // windowed, normalized
      if (t <= 0) continue; // zero element → no contribution (no LUT-floor haze)
      if (t > 1) t = 1;
      let cr: number;
      let cg: number;
      let cb: number;
      if (lut) {
        const o = Math.round(t * 255) * 4;
        cr = lut[o];
        cg = lut[o + 1];
        cb = lut[o + 2];
      } else {
        cr = t * r; // black → colour ramp
        cg = t * g;
        cb = t * b;
      }
      acc[i * 3] += cr * gain;
      acc[i * 3 + 1] += cg * gain;
      acc[i * 3 + 2] += cb * gain;
    }
  });

  const rgba = new Uint8ClampedArray(n * 4); // assignment auto-clamps to [0,255]
  for (let i = 0; i < n; i++) {
    rgba[i * 4] = acc[i * 3];
    rgba[i * 4 + 1] = acc[i * 3 + 1];
    rgba[i * 4 + 2] = acc[i * 3 + 2];
    rgba[i * 4 + 3] = 255;
  }
  return { w, h, rgba };
}
