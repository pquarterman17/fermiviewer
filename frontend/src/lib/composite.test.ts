// compositeChannels — pure multi-channel blend (Quick-Wins #6).

import { describe, expect, it } from "vitest";

import { compositeChannels, type CompositeRaster } from "./composite";

// 2-pixel rasters: first pixel = 0 (zero element), second = full (65535)
function raster(values: number[]): CompositeRaster {
  return { w: values.length, h: 1, data: Uint16Array.from(values) };
}

const px = (rgba: Uint8ClampedArray, i: number) => [
  rgba[i * 4],
  rgba[i * 4 + 1],
  rgba[i * 4 + 2],
  rgba[i * 4 + 3],
];

describe("compositeChannels — solid tint", () => {
  it("full-intensity solid red yields pure red; zero stays black", () => {
    const { rgba } = compositeChannels(
      [raster([0, 65535])],
      [{ color: "#ff0000", intensity: 1, visible: true }],
    );
    expect(px(rgba, 0)).toEqual([0, 0, 0, 255]); // zero element → black
    expect(px(rgba, 1)).toEqual([255, 0, 0, 255]); // full → red
  });

  it("a half-value pixel is half the solid colour (black→colour ramp)", () => {
    const { rgba } = compositeChannels(
      [raster([32768])], // ≈ 0.5
      [{ color: "#ffffff", intensity: 1, visible: true }],
    );
    const [r, g, b] = px(rgba, 0);
    expect(r).toBeGreaterThan(120);
    expect(r).toBeLessThan(136);
    expect(g).toBe(r);
    expect(b).toBe(r);
  });

  it("invisible channels contribute nothing", () => {
    const { rgba } = compositeChannels(
      [raster([65535])],
      [{ color: "#ff0000", intensity: 1, visible: false }],
    );
    expect(px(rgba, 0)).toEqual([0, 0, 0, 255]);
  });
});

describe("compositeChannels — named LUT ramp", () => {
  it("viridis maps full value to its yellow top, mid to teal-ish", () => {
    const { rgba } = compositeChannels(
      [raster([65535, 32768])],
      [{ color: "#000000", cmap: "viridis", intensity: 1, visible: true }],
    );
    const top = px(rgba, 0);
    // viridis top stop ≈ (253, 231, 37): high R+G, low B
    expect(top[0]).toBeGreaterThan(200);
    expect(top[1]).toBeGreaterThan(180);
    expect(top[2]).toBeLessThan(120);
    // mid viridis is green/teal: G is the dominant channel
    const mid = px(rgba, 1);
    expect(mid[1]).toBeGreaterThan(mid[2]);
  });

  it("gray ramp is a neutral black→white (R==G==B)", () => {
    const { rgba } = compositeChannels(
      [raster([65535])],
      [{ color: "#ff0000", cmap: "gray", intensity: 1, visible: true }],
    );
    const [r, g, b] = px(rgba, 0);
    expect(r).toBe(g);
    expect(g).toBe(b);
    expect(r).toBeGreaterThan(250); // full → white, ignores the solid colour
  });
});

describe("compositeChannels — window + additive blend", () => {
  it("a contrast window stretches faint values toward full", () => {
    // value 0.25 with window [0, 0.25] → t=1 → full white
    const { rgba } = compositeChannels(
      [raster([Math.round(0.25 * 65535)])],
      [{ color: "#ffffff", intensity: 1, visible: true, lo: 0, hi: 0.25 }],
    );
    expect(px(rgba, 0)[0]).toBeGreaterThan(250);
  });

  it("two channels add and clamp at 255", () => {
    const { rgba } = compositeChannels(
      [raster([65535]), raster([65535])],
      [
        { color: "#ff0000", intensity: 1, visible: true },
        { color: "#ff0000", intensity: 1, visible: true }, // red + red
      ],
    );
    expect(px(rgba, 0)).toEqual([255, 0, 0, 255]); // clamped, not 510
  });
});
