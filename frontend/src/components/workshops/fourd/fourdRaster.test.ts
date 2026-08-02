import { describe, expect, it } from "vitest";

import { apertureCenterPreview } from "./fourdRaster";

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
});
