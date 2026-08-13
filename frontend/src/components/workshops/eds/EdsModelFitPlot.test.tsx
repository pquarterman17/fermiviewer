import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { EdsPeakfitResult } from "../../../lib/api";
import { BAND_LEGEND_ROW_CLASS } from "../../../lib/charts/sigmaBand";

// Mirrors EelsResults.test.tsx's / EdsModelFit.test.tsx's uPlot mock:
// records what EdsModelFitPlot passes to `new uPlot(...)` without touching
// jsdom's unimplemented canvas 2D context. Lives in vi.hoisted() because
// vi.mock's factory is lifted above every top-level binding in the file.
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

import EdsModelFitPlot from "./EdsModelFitPlot";

const PEAKFIT: EdsPeakfitResult = {
  energy: [0, 0.02, 0.04],
  spectrum: [10, 20, 30],
  model: [9, 19, 31],
  model_sigma: [1, 1.5, 2],
  elements: [
    {
      symbol: "Fe",
      line: "Ka",
      energy_kev: 6.404,
      net_area: 4000,
      net_area_error: 12.3,
      curve: [1, 2, 3],
    },
  ],
  reduced_chi2: 1.234,
  r_squared: 0.987,
  success: true,
};

type Series = { label?: string; class?: string; stroke?: string };

beforeEach(() => {
  mock.state.options = {};
  mock.state.data = undefined;
});

describe("EdsModelFitPlot", () => {
  it("renders nothing when neither cont nor peakfit is given", () => {
    render(<EdsModelFitPlot cont={null} peakfit={null} />);
    expect(mock.state.data).toBeUndefined();
  });

  it("shades the model ±1σ band in the model's own colour when model_sigma is present", () => {
    render(<EdsModelFitPlot cont={null} peakfit={PEAKFIT} />);
    const series = mock.state.options.series as Series[];
    const bandSeries = series.filter((s) => s.class === BAND_LEGEND_ROW_CLASS);
    expect(bandSeries).toHaveLength(2);
    expect(bandSeries[0].stroke).toBe("#22d3ee"); // same colour as "model"
    const modelSeries = series.find((s) => s.label === "model");
    expect(modelSeries?.stroke).toBe("#22d3ee");
    const bands = mock.state.options.bands as { series: [number, number] }[];
    expect(bands).toHaveLength(1);
    const [hi, lo] = bands[0].series;
    expect(series[hi].class).toBe(BAND_LEGEND_ROW_CLASS);
    expect(series[lo].class).toBe(BAND_LEGEND_ROW_CLASS);
  });

  it("renders no band when model_sigma is null", () => {
    render(
      <EdsModelFitPlot cont={null} peakfit={{ ...PEAKFIT, model_sigma: null }} />,
    );
    const series = mock.state.options.series as Series[];
    expect(series.some((s) => s.class === BAND_LEGEND_ROW_CLASS)).toBe(false);
    expect(mock.state.options.bands).toEqual([]);
  });

  it("appends the band AFTER the model + element lines, so their indices don't shift", () => {
    render(<EdsModelFitPlot cont={null} peakfit={PEAKFIT} />);
    const series = mock.state.options.series as Series[];
    // E, spectrum, model, Fe, modelHi, modelLo
    expect(series.map((s) => s.label)).toEqual([
      "E (keV)",
      "spectrum",
      "model",
      "Fe",
      "model ±1σ",
      "model ±1σ",
    ]);
  });

  it("hi/lo data rows are model ± sigma", () => {
    render(<EdsModelFitPlot cont={null} peakfit={PEAKFIT} />);
    const data = mock.state.data as number[][];
    const bands = mock.state.options.bands as { series: [number, number] }[];
    const [hi, lo] = bands[0].series;
    expect(data[hi]).toEqual([10, 20.5, 33]); // model + sigma
    expect(data[lo]).toEqual([8, 17.5, 29]); // model - sigma
  });
});
