import { render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BAND_LEGEND_ROW_CLASS } from "../../lib/charts/sigmaBand";
import { useStageInfo } from "../../store/stage";

// Mirrors EelsFitOverlayPlot.test.tsx's uPlot mock: records what DockPlot
// passes to `new uPlot(...)` without touching jsdom's unimplemented canvas
// 2D context.
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

import DockPlot from "./DockPlot";

type Series = { label?: string; class?: string; stroke?: string };

beforeEach(() => {
  mock.state.options = {};
  mock.state.data = undefined;
});

afterEach(() => {
  useStageInfo.getState().setProfile(null);
});

describe("DockPlot", () => {
  it("renders nothing when there is no active profile", () => {
    const { container } = render(<DockPlot />);
    expect(container).toBeEmptyDOMElement();
  });

  it("draws just the distance/intensity line when intensity_sigma is absent (old server / cached results)", () => {
    useStageInfo.getState().setProfile({
      measureId: "__radial__",
      dist: [0, 1, 2],
      intensity: [10, 20, 30],
      length: 2,
      unit: "px",
      reduce: "mean",
    });
    render(<DockPlot />);
    const series = mock.state.options.series as Series[];
    expect(series).toHaveLength(2);
    expect(mock.state.options.bands).toEqual([]);
    expect(series.some((s) => s.class === BAND_LEGEND_ROW_CLASS)).toBe(false);
  });

  it("shades intensity ± sem when intensity_sigma is present", () => {
    useStageInfo.getState().setProfile({
      measureId: "__radial__",
      dist: [0, 1, 2],
      intensity: [10, 20, 30],
      intensity_sigma: [1, 2, null],
      length: 2,
      unit: "px",
      reduce: "mean",
    });
    render(<DockPlot />);
    const series = mock.state.options.series as Series[];
    expect(series).toHaveLength(4); // x, I, hi, lo
    const bands = mock.state.options.bands as { series: [number, number] }[];
    expect(bands).toHaveLength(1);
    const [hi, lo] = bands[0].series;
    expect(hi).toBe(2);
    expect(lo).toBe(3);
    expect(series[hi].class).toBe(BAND_LEGEND_ROW_CLASS);
    expect(series[lo].class).toBe(BAND_LEGEND_ROW_CLASS);

    const data = mock.state.data as (number | null)[][];
    expect(data[hi]).toEqual([11, 22, null]);
    expect(data[lo]).toEqual([9, 18, null]);
  });

  it("renders a band for a line-profile payload the same way as radial (same field)", () => {
    useStageInfo.getState().setProfile({
      measureId: "m1",
      dist: [0, 1],
      intensity: [5, 6],
      intensity_sigma: [0.5, 0.5],
      length: 1,
      unit: "nm",
      reduce: "mean",
    });
    render(<DockPlot />);
    const bands = mock.state.options.bands as { series: [number, number] }[];
    expect(bands).toHaveLength(1);
  });
});
