import { describe, expect, it } from "vitest";

import {
  formatMapValue,
  mapDisplayRange,
  renderElementMap,
} from "./edsMapDisplay";

describe("EDS map display", () => {
  it("uses percentile contrast without losing the full data range", () => {
    const range = mapDisplayRange([[0, 1, 2, 100]], 0, 75);
    expect(range).toEqual({ dataMin: 0, dataMax: 100, lo: 0, hi: 26.5 });
  });

  it("clamps values through the shared colormap LUT", () => {
    const pixels = renderElementMap(
      [[-1, 0.5, 2]],
      3,
      1,
      { dataMin: -1, dataMax: 2, lo: 0, hi: 1 },
      "gray",
    );
    expect(Array.from(pixels)).toEqual([
      0, 0, 0, 255, 128, 128, 128, 255, 255, 255, 255, 255,
    ]);
  });

  it("formats map values compactly", () => {
    expect(formatMapValue(1234.567)).toBe("1235");
    expect(formatMapValue(0.00042)).toBe("4.20e-4");
  });
});
