// Three-point levelling turns the last angle/triangle measure's normalized
// points into pixel indices; edge points must stay inside the image.
import { describe, expect, it } from "vitest";

import { pixelIndex, threePointPixels } from "./afmMenu";

describe("threePointPixels", () => {
  it("maps a bottom/right-edge point (x = y = 1) to the last pixel", () => {
    expect(pixelIndex(1, 64)).toBe(63);
    expect(pixelIndex(0, 64)).toBe(0);
    expect(threePointPixels([{ x: 1, y: 1 }, { x: 0, y: 1 }, { x: 1, y: 0 }], [64, 128]))
      .toEqual([[63, 127], [63, 0], [0, 127]]);
  });

  it("returns the pixel that contains an interior point", () => {
    expect(threePointPixels([{ x: 0.5, y: 0.25 }], [64, 128])).toEqual([[16, 64]]);
    expect(pixelIndex(0.999, 64)).toBe(63);
  });
});
