import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DefectResult, ImageMeta } from "../../lib/api";
import { useViewer } from "../../store/viewer";

vi.mock("../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/api")>();
  return { ...actual, analyzeDefects: vi.fn() };
});

vi.mock("../../lib/resultsExport", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/resultsExport")>();
  return {
    ...actual,
    downloadCsv: vi.fn(),
    downloadJson: vi.fn(),
  };
});

import { analyzeDefects } from "../../lib/api";
import { downloadCsv, downloadJson } from "../../lib/resultsExport";
import DefectWorkshop, {
  defectRows,
  type DefectRun,
} from "./DefectWorkshop";

function imageMeta(id: string, name = `${id}.dm4`): ImageMeta {
  return {
    id,
    name,
    kind: "image",
    shape: [80, 100],
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

const result: DefectResult = {
  intersections: 14,
  test_lines: 7,
  total_line_length: 320,
  density: 0.0875,
  density_unit: "lines/nm^2",
  pixel_unit: "nm",
  roi: [11, 21, 70, 90],
  h_rows: [20, 40],
  v_cols: [20, 40, 60],
  enhanced: imageMeta("response", "defects(source.dm4)"),
  mask: imageMeta("mask", "defect mask(source.dm4)"),
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

describe("DefectWorkshop", () => {
  it("runs with explicit controls and keeps visual evidence inspectable", async () => {
    vi.mocked(analyzeDefects).mockResolvedValue(result);
    useViewer.getState().ingest([imageMeta("source")]);
    useViewer.getState().setActive("source");
    render(<DefectWorkshop />);

    fireEvent.change(screen.getByLabelText("Direction"), {
      target: { value: "45" },
    });
    fireEvent.change(screen.getByLabelText("Kernel px"), {
      target: { value: "17" },
    });
    fireEvent.change(screen.getByLabelText("Grid px"), {
      target: { value: "20" },
    });
    fireEvent.change(screen.getByLabelText("Foil t (nm)"), {
      target: { value: "30" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Analyze" }));

    await waitFor(() =>
      expect(analyzeDefects).toHaveBeenCalledWith("source", {
        direction: 45,
        kernelLength: 17,
        gridSpacing: 20,
        roi: null,
        foilThickness: 30,
      }),
    );
    expect(await screen.findByText("14")).toBeVisible();
    expect(
      screen.getByRole("img", { name: "Defect test-line grid over the analysis region" }),
    ).toBeVisible();
    expect(screen.getByText(/does not localize individual defects/)).toBeVisible();
    expect(useViewer.getState().images.response).toBeDefined();
    expect(useViewer.getState().images.mask).toBeDefined();
    expect(useViewer.getState().activeId).toBe("source");

    fireEvent.click(screen.getByRole("button", { name: "Inspect mask" }));
    expect(useViewer.getState().activeId).toBe("mask");
    fireEvent.click(screen.getByRole("button", { name: "Source" }));
    expect(useViewer.getState().activeId).toBe("source");

    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    fireEvent.click(screen.getByRole("button", { name: "Export JSON" }));
    expect(downloadCsv).toHaveBeenCalledOnce();
    expect(downloadJson).toHaveBeenCalledOnce();
  });

  it("exports counts, sampled length, and calibrated density", () => {
    const run: DefectRun = {
      result,
      source: imageMeta("source"),
      direction: null,
      kernelLength: 15,
      gridSpacing: 50,
      foilThickness: null,
      regionLabel: "Saved ROI",
    };
    expect(defectRows(run)).toEqual([
      ["intersections", 14, "count"],
      ["test_lines", 7, "count"],
      ["sampled_line_length", 320, "nm"],
      ["density", 0.0875, "lines/nm^2"],
    ]);
  });
});
