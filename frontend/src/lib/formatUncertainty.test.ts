import { describe, expect, it } from "vitest";

import { formatPlusMinus } from "./formatUncertainty";

describe("formatPlusMinus", () => {
  it("formats value ± error with error-tracked precision", () => {
    expect(formatPlusMinus(42.3, 1.5)).toBe("42.3 ± 1.5");
  });

  it("adds decimals for small errors (capped at 3)", () => {
    expect(formatPlusMinus(12.345, 0.05)).toBe("12.345 ± 0.050");
    expect(formatPlusMinus(12.3456, 0.0001)).toBe("12.346 ± 0.000"); // capped
  });

  it("drops the ± term for a zero / non-finite error", () => {
    expect(formatPlusMinus(100, 0)).toBe("100.0");
    expect(formatPlusMinus(100, Number.NaN)).toBe("100.0");
    expect(formatPlusMinus(100, -1)).toBe("100.0");
  });

  it("renders an em dash for a non-finite value", () => {
    expect(formatPlusMinus(Number.NaN, 1)).toBe("—");
  });

  it("honours the minimum-digits floor", () => {
    expect(formatPlusMinus(50, 12, 1)).toBe("50.0 ± 12.0");
  });
});
