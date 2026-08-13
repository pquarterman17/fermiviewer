import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { EelsFitResult, Spectrum } from "../../../lib/api";
import { BAND_LEGEND_ROW_CLASS } from "../../../lib/charts/sigmaBand";

// Mirrors EelsFitResidualPlot's/EdsModelFitPlot's uPlot mock: records what
// EelsFitOverlayPlot passes to `new uPlot(...)` without touching jsdom's
// unimplemented canvas 2D context. Lives in vi.hoisted() because vi.mock's
// factory is lifted above every top-level binding in the file.
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

import EelsFitOverlayPlot from "./EelsFitOverlayPlot";

const SPECTRUM: Spectrum = {
  energy: [400, 401, 402],
  counts: [10, 20, 30],
  units: "eV",
};

const FIT_RESULT: EelsFitResult = {
  energy: [400, 401, 402],
  spectrum: [10, 20, 30],
  model: [9, 19, 31],
  background: [1, 1, 1],
  edges: [
    {
      element: "O",
      shell: "K",
      onset_ev: 532,
      atomic_percent: 66.7,
      atomic_percent_error: 1.2,
      amplitude: 5.1e6,
      amplitude_error: 1.2e5,
      curve: [1, 2, 3],
    },
  ],
  reduced_chi2: 1.234,
  r_squared: 0.987,
  success: true,
  fit_range: [400, 700],
  model_sigma: [1, 1.5, 2],
};

type Series = { label?: string; class?: string; stroke?: string };

beforeEach(() => {
  mock.state.options = {};
  mock.state.data = undefined;
});

describe("EelsFitOverlayPlot", () => {
  it("draws just the raw spectrum when neither fit nor fitResult is given", () => {
    render(
      <EelsFitOverlayPlot
        spectrum={SPECTRUM}
        fit={null}
        fitResult={null}
        showEdges={false}
        elementFilter=""
      />,
    );
    const series = mock.state.options.series as Series[];
    expect(series.map((s) => s.label)).toEqual([undefined, "spectrum"]);
    expect(mock.state.options.bands).toEqual([]);
  });

  it("shades the model ±1σ band in the model's own colour when model_sigma is present", () => {
    render(
      <EelsFitOverlayPlot
        spectrum={SPECTRUM}
        fit={null}
        fitResult={FIT_RESULT}
        showEdges={false}
        elementFilter=""
      />,
    );
    const series = mock.state.options.series as Series[];
    const bandSeries = series.filter((s) => s.class === BAND_LEGEND_ROW_CLASS);
    expect(bandSeries).toHaveLength(2);
    const bands = mock.state.options.bands as { series: [number, number] }[];
    expect(bands).toHaveLength(1);
    const [hi, lo] = bands[0].series;
    expect(series[hi].class).toBe(BAND_LEGEND_ROW_CLASS);
    expect(series[lo].class).toBe(BAND_LEGEND_ROW_CLASS);
  });

  it("renders no band when model_sigma is null", () => {
    render(
      <EelsFitOverlayPlot
        spectrum={SPECTRUM}
        fit={null}
        fitResult={{ ...FIT_RESULT, model_sigma: null }}
        showEdges={false}
        elementFilter=""
      />,
    );
    const series = mock.state.options.series as Series[];
    expect(series.some((s) => s.class === BAND_LEGEND_ROW_CLASS)).toBe(false);
    expect(mock.state.options.bands).toEqual([]);
  });

  it("appends the band AFTER the model/background/edge lines, so their indices don't shift", () => {
    render(
      <EelsFitOverlayPlot
        spectrum={SPECTRUM}
        fit={null}
        fitResult={FIT_RESULT}
        showEdges={false}
        elementFilter=""
      />,
    );
    const series = mock.state.options.series as Series[];
    // x, spectrum, model, bg (fit), O (edge), modelHi, modelLo
    expect(series.map((s) => s.label)).toEqual([
      undefined,
      "spectrum",
      "model",
      "bg (fit)",
      "O",
      "model ±1σ",
      "model ±1σ",
    ]);
  });

  it("hi/lo data rows are model ± sigma", () => {
    render(
      <EelsFitOverlayPlot
        spectrum={SPECTRUM}
        fit={null}
        fitResult={FIT_RESULT}
        showEdges={false}
        elementFilter=""
      />,
    );
    const data = mock.state.data as number[][];
    const bands = mock.state.options.bands as { series: [number, number] }[];
    const [hi, lo] = bands[0].series;
    expect(data[hi]).toEqual([10, 20.5, 33]); // model + sigma
    expect(data[lo]).toEqual([8, 17.5, 29]); // model - sigma
  });
});
