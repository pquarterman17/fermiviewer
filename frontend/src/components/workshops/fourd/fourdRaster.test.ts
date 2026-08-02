import { describe, expect, it } from "vitest";

import type { Raster16 } from "../../../lib/api";
import { apertureCenterPreview, rasterCentroid } from "./fourdRaster";

function raster(w: number, h: number, fill: (y: number, x: number) => number): Raster16 {
  const data = new Uint16Array(w * h);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) data[y * w + x] = fill(y, x);
  }
  return { data, w, h, vmin: 0, vmax: 65535, nFrames: null };
}

describe("apertureCenterPreview", () => {
  it("uses the manual center when autoCenter is off", () => {
    expect(
      apertureCenterPreview(
        { autoCenter: false, centerKy: 3, centerKx: 7 },
        { w: 10, h: 10 },
      ),
    ).toEqual({ cy: 3, cx: 7 });
  });

  it("returns null when autoCenter is off and no manual center is set yet", () => {
    expect(
      apertureCenterPreview(
        { autoCenter: false, centerKy: null, centerKx: null },
        { w: 10, h: 10 },
      ),
    ).toBeNull();
  });

  it("previews the geometric mid-point of the current raster when auto-centered", () => {
    expect(
      apertureCenterPreview(
        { autoCenter: true, centerKy: null, centerKx: null },
        { w: 9, h: 5 },
      ),
    ).toEqual({ cy: 2, cx: 4 });
  });

  it("returns null when auto-centered but no pattern raster has loaded yet", () => {
    expect(
      apertureCenterPreview({ autoCenter: true, centerKy: null, centerKx: null }, null),
    ).toBeNull();
  });

  it("uses the mean pattern's intensity centroid when auto-centered and a mean raster is cached", () => {
    // A single bright pixel well off the geometric mid-point (which would be
    // (4.5, 4.5) for a 10x10 pattern) — the preview must follow the beam,
    // not the detector's geometric center.
    const mean = raster(10, 10, (y, x) => (y === 8 && x === 2 ? 1000 : 0));
    const result = apertureCenterPreview(
      { autoCenter: true, centerKy: null, centerKx: null },
      { w: 10, h: 10 }, // a different pattern (e.g. a probed one) on screen
      mean,
    );
    expect(result).toEqual({ cy: 8, cx: 2 });
  });

  it("falls back to the displayed raster's geometric mid-point when no mean raster is cached yet", () => {
    const result = apertureCenterPreview(
      { autoCenter: true, centerKy: null, centerKx: null },
      { w: 9, h: 5 },
      null,
    );
    expect(result).toEqual({ cy: 2, cx: 4 });
  });
});

describe("rasterCentroid", () => {
  it("finds the centroid of an off-center synthetic blob within 0.1 px", () => {
    // A small Gaussian-ish blob centered at (row 30, col 90) on a 128x128
    // detector — nowhere near the geometric mid-point (63.5, 63.5).
    const trueCy = 30;
    const trueCx = 90;
    const w = 128;
    const h = 128;
    const blob = raster(w, h, (y, x) => {
      const dy = y - trueCy;
      const dx = x - trueCx;
      const r2 = dy * dy + dx * dx;
      return Math.round(5000 * Math.exp(-r2 / (2 * 3 * 3)));
    });
    const { cy, cx } = rasterCentroid(blob.data, w, h);
    expect(Math.abs(cy - trueCy)).toBeLessThan(0.1);
    expect(Math.abs(cx - trueCx)).toBeLessThan(0.1);
  });

  it("falls back to the geometric center for an all-zero pattern", () => {
    const blank = raster(9, 5, () => 0);
    expect(rasterCentroid(blank.data, 9, 5)).toEqual({ cy: 2, cx: 4 });
  });

  it("ignores non-finite samples as zero weight, matching the server's fallback", () => {
    const data = [NaN, NaN, NaN, NaN];
    expect(rasterCentroid(data, 2, 2)).toEqual({ cy: 0.5, cx: 0.5 });
  });
});
