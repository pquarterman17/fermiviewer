import { describe, expect, it } from "vitest";

import { grainParamError } from "./grainWorkflow";

describe("grainParamError", () => {
  it("names the knob the workshop shows, not the wire field", () => {
    expect(grainParamError("gradient", "3", "0")).toBe(
      "coarseness must be between 0 and 1",
    );
    expect(grainParamError("orientation", "-1", "0")).toMatch(/^coarseness/);
    expect(grainParamError("rag", "2", "0")).toMatch(/^merge threshold/);
    expect(grainParamError("kmeans", "40", "0")).toMatch(/^classes/);
    expect(grainParamError("gradient", "0.05", "20")).toMatch(/^denoise/);
  });

  it("accepts in-range values", () => {
    expect(grainParamError("gradient", "0.05", "0")).toBeNull();
    expect(grainParamError("kmeans", "4", "99")).toBeNull(); // no denoise knob
  });
});
