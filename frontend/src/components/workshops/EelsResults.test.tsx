import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { EelsFitResult } from "../../lib/api";

// Mirrors SpectrumPlot.test.tsx's uPlot mock: records what
// EelsFitResidualPlot passes to `new uPlot(...)` without touching
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

import { EelsFitResults } from "./EelsResults";

const RESULT: EelsFitResult = {
  energy: [400, 401, 402],
  spectrum: [10, 20, 30],
  model: [9, 19, 31],
  background: [1, 1, 1],
  edges: [
    {
      element: "O",
      shell: "K",
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
};

beforeEach(() => {
  mock.state.options = {};
  mock.state.data = undefined;
});

describe("EelsFitResults", () => {
  it("renders the χ²ᵣ / R² readout from the response", () => {
    render(<EelsFitResults result={RESULT} />);
    expect(screen.getByText(/χ²ᵣ 1\.23e\+0/)).toBeInTheDocument();
    expect(screen.getByText(/R² 0\.987/)).toBeInTheDocument();
  });

  it("flags a non-converged fit in the same readout", () => {
    render(<EelsFitResults result={{ ...RESULT, success: false }} />);
    expect(screen.getByText(/not converged/)).toBeInTheDocument();
  });

  it("draws the residual trace as observed − model", () => {
    render(<EelsFitResults result={RESULT} />);
    const series = mock.state.options.series as { label?: string }[];
    expect(series.map((s) => s.label)).toEqual([undefined, "residual"]);
    const data = mock.state.data as unknown[];
    expect(data[0]).toEqual(RESULT.energy);
    // 10-9, 20-19, 30-31
    expect(data[1]).toEqual([1, 1, -1]);
  });

  it("skips the residual plot when the response arrays are ragged", () => {
    render(
      <EelsFitResults
        result={{ ...RESULT, model: [9, 19] /* length mismatch */ }}
      />,
    );
    // no uPlot instance should have been built for this render
    expect(mock.state.data).toBeUndefined();
  });
});
