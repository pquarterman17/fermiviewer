import { describe, expect, it } from "vitest";

import { heightAnalysisKey } from "./analysisFreshness";

describe("heightAnalysisKey", () => {
  it("changes with the region identity, geometry, or background removal", () => {
    const base = heightAnalysisKey("selected", [1, 2, 30, 40], "plane");
    expect(heightAnalysisKey("saved:a", [1, 2, 30, 40], "plane")).not.toBe(base);
    expect(heightAnalysisKey("selected", [1, 2, 31, 40], "plane")).not.toBe(base);
    expect(heightAnalysisKey("selected", [1, 2, 30, 40], "quadratic")).not.toBe(base);
  });

  it("is stable for repeated whole-image settings", () => {
    expect(heightAnalysisKey("whole", null, "none"))
      .toBe(heightAnalysisKey("whole", null, "none"));
  });
});
