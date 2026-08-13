import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { EelsFitResult } from "../../lib/api";

// mock the download seam the "Export fit report (CSV)" button uses — the
// same module every other workshop's CSV export mocks in its tests
vi.mock("../../lib/eelsQuantCsv", async (importActual) => {
  const actual =
    await importActual<typeof import("../../lib/eelsQuantCsv")>();
  return { ...actual, downloadCsv: vi.fn() };
});

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

import { downloadCsv } from "../../lib/eelsQuantCsv";
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
  model_sigma: null,
};

beforeEach(() => {
  mock.state.options = {};
  mock.state.data = undefined;
  vi.mocked(downloadCsv).mockClear();
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

  it("downloads a fit report CSV with the fit stats and per-edge rows (#7)", () => {
    render(<EelsFitResults result={RESULT} imageName="sample.dm4" />);
    fireEvent.click(
      screen.getByRole("button", { name: "Export fit report (CSV)" }),
    );
    expect(downloadCsv).toHaveBeenCalledOnce();
    const [filename, csv] = vi.mocked(downloadCsv).mock.calls[0];
    expect(filename).toBe("sample_eels_fit_report.csv");
    expect(csv).toContain("# fermiviewer EELS fit report");
    expect(csv).toContain("# fit_range_ev: 400-700");
    expect(csv).toContain("O,K,532,5100000,120000,66.7,1.2");
  });

  it("falls back to a generic name when no image name is given", () => {
    render(<EelsFitResults result={RESULT} />);
    fireEvent.click(
      screen.getByRole("button", { name: "Export fit report (CSV)" }),
    );
    const [filename] = vi.mocked(downloadCsv).mock.calls[0];
    expect(filename).toBe("image_eels_fit_report.csv");
  });
});
