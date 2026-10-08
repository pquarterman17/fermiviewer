import { describe, expect, it } from "vitest";

import { clampScaleBarFont } from "./scaleBarFont";

describe("clampScaleBarFont", () => {
  it("clamps, rounds and passes null through", () => {
    expect(clampScaleBarFont(500)).toBe(120);
    expect(clampScaleBarFont(2)).toBe(8);
    expect(clampScaleBarFont(40.4)).toBe(40);
    expect(clampScaleBarFont(null)).toBeNull();
    expect(clampScaleBarFont(Number.NaN)).toBeNull();
  });
});
