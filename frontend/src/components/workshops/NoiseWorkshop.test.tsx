import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ImageMeta, NoiseResult } from "../../lib/api";
import { useViewer } from "../../store/viewer";
import { useWorkshop } from "../../store/workshop";

vi.mock("uplot", () => ({
  default: class {
    destroy() {}
  },
}));

vi.mock("../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/api")>();
  return {
    ...actual,
    analyzeNoise: vi.fn(),
    applyFilter: vi.fn(),
  };
});

vi.mock("../../lib/resultsExport", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/resultsExport")>();
  return {
    ...actual,
    downloadCsv: vi.fn(),
    downloadJson: vi.fn(),
  };
});

import { analyzeNoise, applyFilter } from "../../lib/api";
import { downloadCsv, downloadJson } from "../../lib/resultsExport";
import NoiseWorkshop, { noiseRows } from "./NoiseWorkshop";

const result: NoiseResult = {
  sigma: 2.5,
  snr_db: 26.02,
  snr_linear: 20,
  noise_type: "poisson",
  method: "mad",
  recommendation: "median (window 3–5)",
  roi: null,
  n_pixels: 4096,
  block_size: 16,
  n_blocks: 16,
  block_means: [10, 20, 30, 40],
  block_variances: [11, 19, 31, 39],
  regression_slope: 0.96,
  regression_intercept: 0.4,
  regression_r_squared: 0.98,
};

function imageMeta(id = "source"): ImageMeta {
  return {
    id,
    name: `${id}.dm4`,
    kind: "image",
    shape: [64, 64],
    dtype: "float32",
    pixel_size: 0.5,
    pixel_unit: "nm",
    value_unit: "",
    n_channels: null,
    energy_first: null,
    energy_last: null,
    energy_units: "",
    stage_tilt_deg: null,
    meta: {},
  };
}

const savedRoi = {
  id: "r1", name: "Terrace", kind: "roi" as const, createdAt: "2026-01-01T00:00:00Z",
  pts: [{ x: 4, y: 4 }, { x: 20, y: 20 }],
};

afterEach(() => {
  vi.clearAllMocks();
  useViewer.setState({
    images: {},
    order: [],
    activeId: null,
    selected: [],
    savedRois: {},
    measures: {},
  });
});

describe("NoiseWorkshop", () => {
  it("shows persistent diagnostics and applies the recommended filter", async () => {
    vi.mocked(analyzeNoise).mockResolvedValue(result);
    vi.mocked(applyFilter).mockResolvedValue(imageMeta("denoised"));
    useViewer.getState().ingest([imageMeta()]);
    useViewer.getState().setActive("source");

    render(<NoiseWorkshop />);
    fireEvent.click(screen.getByRole("button", { name: "Analyze" }));

    await waitFor(() =>
      expect(analyzeNoise).toHaveBeenCalledWith("source", {
        method: "mad",
        roi: null,
        signal: expect.any(AbortSignal),
      }),
    );
    expect(await screen.findByText("2.500")).toBeVisible();
    expect(screen.getByText("Classification evidence: variance vs mean")).toBeVisible();
    expect(screen.getByText(/Recommendation: median/)).toBeVisible();

    fireEvent.click(
      screen.getByRole("button", { name: "Apply recommended filter" }),
    );
    await waitFor(() =>
      expect(applyFilter).toHaveBeenCalledWith(
        "source",
        "median",
        { window_size: 3 },
        { signal: expect.any(AbortSignal) },
      ),
    );
    expect(useViewer.getState().images.denoised).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    fireEvent.click(screen.getByRole("button", { name: "Export JSON" }));
    expect(downloadCsv).toHaveBeenCalledOnce();
    expect(downloadJson).toHaveBeenCalledOnce();
  });

  it("marks an existing result stale when the estimator changes", async () => {
    vi.mocked(analyzeNoise).mockResolvedValue(result);
    useViewer.getState().ingest([imageMeta()]);
    useViewer.getState().setActive("source");
    render(<NoiseWorkshop />);
    fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
    await screen.findByText("2.500");
    fireEvent.change(screen.getByLabelText("Estimator"), {
      target: { value: "localvar" },
    });
    expect(screen.getByRole("status")).toHaveTextContent("rerun");
  });

  it("exports every visible scalar diagnostic", () => {
    expect(noiseRows(result)).toEqual([
      ["sigma", 2.5, "intensity"],
      ["snr_linear", 20, "ratio"],
      ["snr_db", 26.02, "dB"],
      ["noise_type", "poisson", ""],
      ["regression_slope", 0.96, ""],
      ["regression_intercept", 0.4, ""],
      ["regression_r_squared", 0.98, ""],
    ]);
  });

  it("labels the result with the region it was measured on", async () => {
    vi.mocked(analyzeNoise).mockResolvedValue(result);
    useViewer.getState().ingest([imageMeta()]);
    useViewer.setState({ savedRois: { source: [savedRoi] } });
    useViewer.getState().setActive("source");
    useWorkshop.getState().setAnalysisRegionChoice("source", "saved:r1");
    render(<NoiseWorkshop />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
    });
    // choosing another region afterwards does not relabel the old result
    act(() => useWorkshop.getState().setAnalysisRegionChoice("source", "whole"));
    expect(screen.getByText(/· Terrace ·/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Export JSON" }));
    expect(JSON.stringify(vi.mocked(downloadJson).mock.calls[0][1])).toContain("Terrace");
  });

  it("aborts and drops a noise result after the active image changes", async () => {
    let resolve!: (value: NoiseResult) => void;
    vi.mocked(analyzeNoise).mockReturnValue(
      new Promise((next) => { resolve = next; }),
    );
    useViewer.getState().ingest([imageMeta("a"), imageMeta("b")]);
    useViewer.getState().setActive("a");
    render(<NoiseWorkshop />);

    fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
    const signal = vi.mocked(analyzeNoise).mock.calls[0]![1]!.signal!;
    act(() => useViewer.getState().setActive("b"));
    await act(async () => resolve(result));

    expect(signal.aborted).toBe(true);
    expect(screen.queryByText("2.500")).toBeNull();
    expect(screen.queryByRole("button", { name: "Export CSV" })).toBeNull();
    expect(screen.getByRole("button", { name: "Analyze" })).not.toBeDisabled();
  });

  it("does not ingest a recommended filter after the source changes", async () => {
    vi.mocked(analyzeNoise).mockResolvedValue(result);
    let resolve!: (value: ImageMeta) => void;
    vi.mocked(applyFilter).mockReturnValue(
      new Promise((next) => { resolve = next; }),
    );
    useViewer.getState().ingest([imageMeta("a"), imageMeta("b")]);
    useViewer.getState().setActive("a");
    render(<NoiseWorkshop />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
    });

    fireEvent.click(
      screen.getByRole("button", { name: "Apply recommended filter" }),
    );
    const signal = vi.mocked(applyFilter).mock.calls[0]![3]!.signal!;
    act(() => useViewer.getState().setActive("b"));
    await act(async () => resolve(imageMeta("denoised-a")));

    expect(signal.aborted).toBe(true);
    expect(useViewer.getState().images).not.toHaveProperty("denoised-a");
    expect(useViewer.getState().activeId).toBe("b");
  });
});
