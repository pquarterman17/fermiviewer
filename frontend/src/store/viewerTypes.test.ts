import { describe, expect, it } from "vitest";

import { OVERLAY_FONT_PX, sanitizeOverlay, type OverlayStyle } from "./viewerTypes";

const BASE: OverlayStyle = { size: "L", color: "#ffffff", lineWidth: 2.5, endSymbol: "bar" };

describe("sanitizeOverlay", () => {
  it("keeps valid fields", () => {
    const o = { size: "XS", color: "#ff0000", lineWidth: 3, endSymbol: "cross" };
    expect(sanitizeOverlay(o, BASE)).toEqual(o);
  });

  it("replaces bad fields so the label font is never undefined", () => {
    const o = sanitizeOverlay({ size: "HUGE", lineWidth: -1, endSymbol: "star", color: 7 }, BASE);
    expect(o).toEqual(BASE);
    expect(OVERLAY_FONT_PX[o.size]).toBe(40);
  });

  it("handles a missing/non-object value", () => {
    expect(sanitizeOverlay(null, BASE)).toEqual(BASE);
    expect(sanitizeOverlay("x", BASE)).toEqual(BASE);
  });
});
