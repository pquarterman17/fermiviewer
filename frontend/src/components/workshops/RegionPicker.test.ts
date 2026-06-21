// RegionPicker pixel-mapping helpers (Quick-Wins #2 EELS specnav):
// view-space → 1-based image pixel, and click → 1×1 rect.

import { describe, expect, it } from "vitest";

import { clickPixelRect, viewToImagePx } from "./RegionPicker";

describe("viewToImagePx", () => {
  it("maps a view coordinate to a 1-based image pixel, clamped", () => {
    // a 64 px image shown at 300 px → scale = 300/64 ≈ 4.6875
    const scale = 300 / 64;
    expect(viewToImagePx(0, scale, 64)).toBe(1); // top-left clamps to 1
    expect(viewToImagePx(299, scale, 64)).toBe(64); // bottom clamps to n
    // a click ~halfway lands near the middle pixel
    expect(viewToImagePx(150, scale, 64)).toBe(33);
  });

  it("never returns below 1 or above n", () => {
    expect(viewToImagePx(-50, 4, 32)).toBe(1);
    expect(viewToImagePx(99999, 4, 32)).toBe(32);
  });
});

describe("clickPixelRect (specnav)", () => {
  it("produces a 1×1 inclusive rect at the clicked pixel", () => {
    const scale = 300 / 64;
    const [r0, c0, r1, c1] = clickPixelRect(150, 75, scale, 64, 64);
    expect(r0).toBe(r1); // single row
    expect(c0).toBe(c1); // single col
    expect(r0).toBe(viewToImagePx(75, scale, 64));
    expect(c0).toBe(viewToImagePx(150, scale, 64));
  });

  it("respects independent width/height bounds", () => {
    // wide-but-short cube: 128 wide, 16 tall
    const scale = 300 / 128;
    const rect = clickPixelRect(299, 299, scale, 128, 16);
    expect(rect).toEqual([16, 128, 16, 128]); // clamped per axis
  });
});
