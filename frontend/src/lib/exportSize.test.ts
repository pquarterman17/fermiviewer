import { describe, expect, it } from "vitest";

import { exportOutputSize, exportTooLarge } from "./exportSize";

describe("exportOutputSize", () => {
  it("adds the caption band the backend appends (6 px figure → 6×78)", () => {
    // 1 mm @ 150 dpi = 6 px wide: each word of the caption wraps to its own
    // 15 px line inside a 6 px-padded band (routes/_export_render.py)
    const out = exportOutputSize(6, 6, {
      format: "png",
      scale: 0.01,
      colorbar: false,
      caption: "Fig 1 a b",
    });
    expect(out).toEqual({ w: 6, h: 6 + 12 + 15 * 4 });
  });

  it("adds the colorbar gutter and ignores overlays for tiff16", () => {
    const o = { scale: 1, colorbar: true, caption: "x" };
    expect(exportOutputSize(100, 50, { ...o, format: "png" })).toEqual({
      w: 181,
      h: 50 + 12 + 15,
    });
    expect(exportOutputSize(100, 50, { ...o, format: "svg" })).toEqual({
      w: 181,
      h: 50 + 12 + 17,
    });
    expect(exportOutputSize(100, 50, { ...o, format: "tiff16" })).toEqual({
      w: 100,
      h: 50,
    });
  });
});

describe("exportTooLarge", () => {
  it("allows a 4096² frame at 4× but refuses 2000 mm @ 600 dpi", () => {
    expect(exportTooLarge(16384, 16384)).toBe(false);
    expect(exportTooLarge(47244, 47244)).toBe(true);
    expect(exportTooLarge(25000, 100)).toBe(true);
  });
});
