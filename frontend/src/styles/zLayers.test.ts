import { describe, expect, it } from "vitest";

import { MODAL_BACKDROP, TOOL_WINDOW_BASE, toolWindowZIndex } from "./zLayers";

describe("zLayers", () => {
  it("places a freshly-opened tool window below the modal layer", () => {
    // z=1 is the very first tool a session opens — this is the exact
    // scenario the usability audit observed (one 4D-STEM tool window open,
    // opening Batch/Export rendered them partly behind it).
    expect(toolWindowZIndex(1)).toBe(TOOL_WINDOW_BASE + 1);
    expect(toolWindowZIndex(1)).toBeLessThan(MODAL_BACKDROP);
  });

  it("clamps unbounded per-session focus counters below the modal layer", () => {
    for (const z of [0, 5, 50, 90, 91, 500, 100_000]) {
      expect(toolWindowZIndex(z)).toBeLessThan(MODAL_BACKDROP);
    }
  });

  it("never returns a value below TOOL_WINDOW_BASE for negative input", () => {
    expect(toolWindowZIndex(-5)).toBe(TOOL_WINDOW_BASE);
  });
});
