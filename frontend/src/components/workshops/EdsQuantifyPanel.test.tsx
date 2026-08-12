import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CompositionProfileResult } from "../../lib/api";
import { BAND_LEGEND_ROW_CLASS } from "../../lib/charts/sigmaBand";

// Mirrors EelsResults.test.tsx's uPlot mock: records what CompProfilePlot
// passes to `new uPlot(...)` without touching jsdom's unimplemented canvas
// 2D context. Lives in vi.hoisted() because vi.mock's factory is lifted
// above every top-level binding in the file.
const mock = vi.hoisted(() => {
  const state = {
    options: {} as Record<string, unknown>,
    data: undefined as unknown,
  };
  class Plot {
    constructor(
      options: Record<string, unknown>,
      data: unknown,
      host: HTMLElement,
    ) {
      state.options = options;
      state.data = data;
      host.appendChild(document.createElement("canvas"));
    }
    destroy() {}
    setSize() {}
  }
  return { state, Plot };
});
vi.mock("uplot", () => ({ default: mock.Plot }));

import { CompProfilePlot } from "./EdsQuantifyPanel";

const RESULT: CompositionProfileResult = {
  distance: [0, 1, 2, 3],
  atomic_pct: [
    [90, 60, 30, 10], // Cu
    [10, 40, 70, 90], // Ni
  ],
  atomic_percent_error: [
    [1, 1.5, 2, 1],
    [0.5, 1, 1.5, 0.8],
  ],
  elements: ["Cu", "Ni"],
  unit: "nm",
};

beforeEach(() => {
  mock.state.options = {};
  mock.state.data = undefined;
});

type Series = { label?: string; class?: string; show?: boolean };

describe("CompProfilePlot", () => {
  it("keeps the main element lines at series[1..n], matching atomic_pct's own order", () => {
    render(<CompProfilePlot r={RESULT} />);
    const series = mock.state.options.series as Series[];
    expect(series[0]).toEqual({ label: "d (nm)" });
    expect(series[1].label).toBe("Cu");
    expect(series[2].label).toBe("Ni");
    // legend-click → series index mapping for an element is `elements`
    // order + 1 (x is index 0) -- this must survive appending bands after.
    expect(RESULT.elements.indexOf("Cu")).toBe(0);
    expect(RESULT.elements.indexOf("Ni")).toBe(1);
  });

  it("appends one hi/lo band-boundary pair per element AFTER the main lines", () => {
    render(<CompProfilePlot r={RESULT} />);
    const series = mock.state.options.series as Series[];
    // x + 2 main lines + 2 elements * (hi, lo) = 7 series total
    expect(series).toHaveLength(7);
    for (const s of series.slice(3)) {
      expect(s.class).toBe(BAND_LEGEND_ROW_CLASS);
      expect(s.show).toBe(true); // bands only fill when both edges are shown
    }
  });

  it("wires bands[] to the exact series indices of each element's hi/lo pair", () => {
    render(<CompProfilePlot r={RESULT} />);
    const bands = mock.state.options.bands as { series: [number, number] }[];
    expect(bands.map((b) => b.series)).toEqual([
      [3, 4], // Cu: hi=3, lo=4 (after x@0, Cu@1, Ni@2)
      [5, 6], // Ni: hi=5, lo=6
    ]);
  });

  it("hi/lo data rows are y ± sigma for the matching element", () => {
    render(<CompProfilePlot r={RESULT} />);
    const data = mock.state.data as number[][];
    // data layout: [distance, Cu, Ni, CuHi, CuLo, NiHi, NiLo]
    expect(data[3]).toEqual([91, 61.5, 32, 11]); // Cu + sigma
    expect(data[4]).toEqual([89, 58.5, 28, 9]); // Cu - sigma
    expect(data[5]).toEqual([10.5, 41, 71.5, 90.8]); // Ni + sigma
    expect(data[6]).toEqual([9.5, 39, 68.5, 89.2]); // Ni - sigma
  });

  it("renders no band series when the response carries no sigma (older/degraded response)", () => {
    const noSigma: CompositionProfileResult = {
      ...RESULT,
      atomic_percent_error: undefined,
    };
    render(<CompProfilePlot r={noSigma} />);
    const series = mock.state.options.series as Series[];
    expect(series).toHaveLength(3); // x + Cu + Ni, no band pairs
    expect(mock.state.options.bands).toEqual([]);
  });
});
