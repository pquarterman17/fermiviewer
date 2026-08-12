// components/analysis/PopulationHistogram.tsx (ANALYSIS_PRESENTATION_PLAN.md
// #6, audit R6). Mocks "uplot" the same way SpectrumPlot.test.tsx does
// (jsdom has no real canvas 2D context) so these tests exercise the
// component's data flow — what gets fetched, what gets rendered into the
// mock plot's data array, and what the summary line says — rather than
// pixel output, which lib/populationHistogram.test.ts already pins via
// the pure pdf-scaling math.

import { render, screen, waitFor } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

interface MockPlotOptions {
  series?: { paths?: unknown }[];
  hooks?: { draw?: ((u: unknown) => void)[] };
}

const mock = vi.hoisted(() => {
  const state = {
    options: {} as MockPlotOptions,
    data: null as unknown,
    instances: 0,
  };

  class Plot {
    constructor(options: MockPlotOptions, data: unknown, host: HTMLElement) {
      state.options = options;
      state.data = data;
      state.instances += 1;
      host.appendChild(document.createElement("canvas"));
    }
    destroy() {}
    setSize() {}
  }
  (Plot as unknown as { paths: unknown }).paths = {
    bars: vi.fn(() => vi.fn()),
  };

  return { state, Plot };
});

vi.mock("uplot", () => ({ default: mock.Plot }));

vi.mock("../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/api")>();
  return { ...actual, analyzeDistribution: vi.fn() };
});

import { analyzeDistribution, type DistributionResult } from "../../lib/api";
import PopulationHistogram from "./PopulationHistogram";

beforeAll(() => {
  class ResizeObserverStub {
    observe() {}
    disconnect() {}
  }
  Object.defineProperty(globalThis, "ResizeObserver", {
    configurable: true,
    value: ResizeObserverStub,
  });
});

beforeEach(() => {
  vi.clearAllMocks();
  mock.state.instances = 0;
});

function sampleResult(best: "normal" | "lognormal" | "weibull" = "lognormal"): DistributionResult {
  return {
    summary: {
      n: 300,
      n_dropped: 0,
      mean: 18.4,
      std: 3.2,
      min: 8.1,
      max: 32.5,
      median: 17.9,
      q1: 15.1,
      q3: 21.0,
    },
    histogram: {
      edges: [8, 12, 16, 20, 24, 28, 32],
      counts: [10, 60, 110, 80, 30, 10],
    },
    fits: {
      normal: {
        kind: "normal",
        params: { loc: 18.4, scale: 3.2 },
        log_likelihood: -800,
        aic: 1604,
        ks_statistic: 0.09,
        ks_pvalue: 0.02,
      },
      lognormal: {
        kind: "lognormal",
        params: { s: 0.18, loc: 0, scale: 18.0 },
        log_likelihood: -780,
        aic: 1564,
        ks_statistic: 0.03,
        ks_pvalue: 0.61,
      },
      weibull: {
        kind: "weibull",
        params: { c: 5.2, loc: 0, scale: 20.0 },
        log_likelihood: -790,
        aic: 1584,
        ks_statistic: 0.05,
        ks_pvalue: 0.31,
      },
      best,
    },
  };
}

describe("PopulationHistogram", () => {
  it("fetches once, renders bars from the histogram, and shows the summary line", async () => {
    vi.mocked(analyzeDistribution).mockResolvedValue(sampleResult());

    render(<PopulationHistogram values={[10, 11, 12]} unit="nm" />);

    await waitFor(() => expect(mock.state.instances).toBe(1));
    expect(analyzeDistribution).toHaveBeenCalledTimes(1);
    expect(analyzeDistribution).toHaveBeenCalledWith([10, 11, 12], "all");

    // bar series data: x = bin centers, y = counts (see lib/populationHistogram binCenters)
    const [xs, ys] = mock.state.data as [number[], number[]];
    expect(xs).toEqual([10, 14, 18, 22, 26, 30]);
    expect(ys).toEqual([10, 60, 110, 80, 30, 10]);

    // summary line: N, mean ± std, median [q1, q3] with the unit
    expect(screen.getByText(/N=300/)).toBeInTheDocument();
    expect(screen.getByText(/median 17\.90 \[15\.10, 21\.00\] nm/)).toBeInTheDocument();
  });

  it("defaults the selector to Best and shows that fit's AIC", async () => {
    vi.mocked(analyzeDistribution).mockResolvedValue(sampleResult("lognormal"));

    render(<PopulationHistogram values={[10, 11, 12]} unit="nm" />);
    await waitFor(() => expect(mock.state.instances).toBe(1));

    expect(screen.getByLabelText("Distribution")).toHaveValue("best");
    expect(screen.getByText(/AIC 1564\.0/)).toBeInTheDocument(); // lognormal's AIC
  });

  it("switches the drawn fit when the selector changes, without refetching", async () => {
    vi.mocked(analyzeDistribution).mockResolvedValue(sampleResult("lognormal"));

    render(<PopulationHistogram values={[10, 11, 12]} unit="nm" />);
    await waitFor(() => expect(mock.state.instances).toBe(1));

    const select = screen.getByLabelText("Distribution") as HTMLSelectElement;
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.change(select, { target: { value: "weibull" } });

    await waitFor(() => expect(screen.getByText(/AIC 1584\.0/)).toBeInTheDocument());
    // still exactly one fetch — the selector switches client-side
    expect(analyzeDistribution).toHaveBeenCalledTimes(1);
  });

  it("falls back to a histogram-only request when the population is too small to fit", async () => {
    const tooSmall: DistributionResult = { ...sampleResult(), fits: null };
    vi.mocked(analyzeDistribution)
      .mockRejectedValueOnce(new Error("need at least 8 finite values to fit a distribution, got 3"))
      .mockResolvedValueOnce(tooSmall);

    render(<PopulationHistogram values={[10, 11, 12]} unit="nm" />);

    await waitFor(() => expect(analyzeDistribution).toHaveBeenCalledTimes(2));
    expect(analyzeDistribution).toHaveBeenNthCalledWith(1, [10, 11, 12], "all");
    expect(analyzeDistribution).toHaveBeenNthCalledWith(2, [10, 11, 12], "none");
    expect(screen.getByText(/too few objects to fit/)).toBeInTheDocument();
    expect(screen.getByLabelText("Distribution")).toBeDisabled();
  });

  it("renders nothing to fetch for an empty population", () => {
    render(<PopulationHistogram values={[]} unit="nm" />);
    expect(analyzeDistribution).not.toHaveBeenCalled();
    expect(screen.getByText("No values to summarize.")).toBeInTheDocument();
  });
});
