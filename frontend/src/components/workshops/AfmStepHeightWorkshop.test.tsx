import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ImageMeta, StepHeightResult } from "../../lib/api";
import { useViewer } from "../../store/viewer";

vi.mock("../../hooks/useAnalysisRoi", () => ({
  useAnalysisRoi: () => ({
    choice: "last", roi: [4, 6, 40, 32], label: "Last ROI",
    options: [{ value: "last", label: "Last ROI" }], setChoice: vi.fn(),
  }),
}));
vi.mock("../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/api")>();
  return { ...actual, afmStepHeight: vi.fn() };
});
vi.mock("../../lib/resultsExport", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/resultsExport")>();
  return { ...actual, downloadCsv: vi.fn(), downloadJson: vi.fn() };
});

import { afmStepHeight } from "../../lib/api";
import { downloadCsv } from "../../lib/resultsExport";
import AfmStepHeightWorkshop, { stepHeightRows } from "./AfmStepHeightWorkshop";
import { stepWarnings } from "./AfmStepEvidence";

const result: StepHeightResult = {
  height: 4.25, lower_std: 0.12, upper_std: 0.18,
  n_lower: 600, n_upper: 400, upper_fraction: 0.4,
  unit: "nm", roi: [4, 6, 40, 32],
  signed_height: 4.25, profile_axis: "x",
  profile_position: [0, 1, 2], profile_measured: [0, 0, 4.25],
  profile_fitted: [0, 0, 4.25], profile_residual: [0.1, -0.1, 0],
  profile_upper_fraction: [0, 0, 1], terrace_mask: [[1, 1, 2]],
  slope_x: 0.01, slope_y: 0, fit_rms: 0.15,
  split_axis: null, split_fraction: null,
};

const image: ImageMeta = {
  id: "a", name: "Height", kind: "image", shape: [64, 64], dtype: "float32",
  pixel_size: 1, pixel_unit: "nm", value_unit: "nm", n_channels: null,
  energy_first: null, energy_last: null, energy_units: "", stage_tilt_deg: null,
  meta: { parser: "nanoscope", channel: "Height" },
};

beforeEach(() => {
  vi.mocked(afmStepHeight).mockReset();
  vi.mocked(downloadCsv).mockClear();
  useViewer.setState({ activeId: "a", images: { a: image }, status: "" });
});

describe("AfmStepHeightWorkshop", () => {
  it("keeps the measurement visible with terrace quality and provenance", async () => {
    vi.mocked(afmStepHeight).mockResolvedValue(result);
    render(<AfmStepHeightWorkshop />);
    fireEvent.click(screen.getByRole("button", { name: "Measure" }));

    expect(await screen.findByText("4.250 nm")).toBeVisible();
    expect(screen.getByText("600 / 400")).toBeVisible();
    expect(screen.getByText("40.0%")).toBeVisible();
    expect(afmStepHeight).toHaveBeenCalledWith("a", [4, 6, 40, 32], 2);

    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    expect(downloadCsv).toHaveBeenCalledOnce();
  });

  it("marks results stale and blocks export when edge exclusion changes", async () => {
    vi.mocked(afmStepHeight).mockResolvedValue(result);
    render(<AfmStepHeightWorkshop />);
    fireEvent.click(screen.getByRole("button", { name: "Measure" }));
    await screen.findByText("4.250 nm");

    fireEvent.change(screen.getByLabelText("Ignore step edge"), { target: { value: "5" } });
    expect(screen.getByRole("status")).toHaveTextContent("update the measurement");
    expect(screen.getByRole("button", { name: "Export CSV" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Update measurement" })).toBeEnabled();
  });

  it("ignores a response after the active image changes", async () => {
    let resolve!: (value: StepHeightResult) => void;
    vi.mocked(afmStepHeight).mockReturnValue(new Promise((done) => { resolve = done; }));
    render(<AfmStepHeightWorkshop />);
    fireEvent.click(screen.getByRole("button", { name: "Measure" }));
    useViewer.setState({ activeId: null });
    resolve(result);
    await waitFor(() => expect(screen.queryByText("4.250 nm")).toBeNull());
  });

  it("sends an explicit manual terrace split", async () => {
    vi.mocked(afmStepHeight).mockResolvedValue(result);
    render(<AfmStepHeightWorkshop />);
    fireEvent.click(screen.getByLabelText("Correct terrace split manually"));
    fireEvent.change(screen.getByLabelText("Direction"), { target: { value: "y" } });
    fireEvent.change(screen.getByLabelText("Split"), { target: { value: "60" } });
    fireEvent.click(screen.getByRole("button", { name: "Measure" }));
    await screen.findByText("4.250 nm");
    expect(afmStepHeight).toHaveBeenCalledWith("a", [4, 6, 40, 32], 2, { axis: "y", fraction: 0.6 });
  });
});

it("builds standard measurement export rows", () => {
  expect(stepHeightRows(result)).toEqual(expect.arrayContaining([
    ["Step height", 4.25, "nm"],
    ["Upper terrace fraction", 40, "%"],
  ]));
});

it("flags visibly weak and unbalanced terrace evidence", () => {
  expect(stepWarnings({ ...result, height: 0.2, fit_rms: 0.1, upper_fraction: 0.05 }))
    .toEqual(expect.arrayContaining([
      expect.stringContaining("Weak terrace separation"),
      expect.stringContaining("strongly unequal"),
      expect.stringContaining("residuals are large"),
    ]));
});
