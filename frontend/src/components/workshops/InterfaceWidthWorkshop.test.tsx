import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ImageMeta, InterfaceWidthResult } from "../../lib/api";
import { useStageInfo } from "../../store/stage";
import { useViewer } from "../../store/viewer";

vi.mock("../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/api")>();
  return { ...actual, analyzeInterfaceWidth: vi.fn() };
});

vi.mock("../../lib/resultsExport", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/resultsExport")>();
  return {
    ...actual,
    downloadCsv: vi.fn(),
    downloadJson: vi.fn(),
  };
});

import { analyzeInterfaceWidth } from "../../lib/api";
import { downloadCsv, downloadJson } from "../../lib/resultsExport";
import InterfaceWidthWorkshop, {
  interfaceWidthRows,
  type FitRun,
} from "./InterfaceWidthWorkshop";

const result: InterfaceWidthResult = {
  center: 5,
  sigma: 1.2,
  width_10_90: 3.08,
  amplitude: 20,
  offset: 4,
  r_squared: 0.992,
  x_fit: [0, 2.5, 5, 7.5, 10],
  y_fit: [4, 5, 14, 23, 24],
  model: "erf",
};

function imageMeta(): ImageMeta {
  return {
    id: "source",
    name: "interface.dm4",
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

afterEach(() => {
  vi.clearAllMocks();
  useStageInfo.getState().setProfile(null);
  useViewer.setState({
    images: {},
    order: [],
    activeId: null,
    selected: [],
  });
});

describe("InterfaceWidthWorkshop", () => {
  it("guides the user when no dock profile exists", () => {
    render(<InterfaceWidthWorkshop />);
    expect(screen.getByText(/Draw or select a line\/profile/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Fit profile" })).toBeDisabled();
  });

  it("fits, visualizes, and exports the complete result", async () => {
    vi.mocked(analyzeInterfaceWidth).mockResolvedValue(result);
    useViewer.getState().ingest([imageMeta()]);
    useViewer.getState().setActive("source");
    useStageInfo.getState().setProfile({
      dist: [0, 2.5, 5, 7.5, 10],
      intensity: [4, null, 14, 23, 24],
      length: 10,
      unit: "nm",
      reduce: "mean",
      measureId: "m1",
    });
    render(<InterfaceWidthWorkshop />);
    fireEvent.click(screen.getByRole("button", { name: "Fit profile" }));

    await waitFor(() =>
      expect(analyzeInterfaceWidth).toHaveBeenCalledWith(
        [0, 2.5, 5, 7.5, 10],
        [4, null, 14, 23, 24],
        "erf",
      ),
    );
    expect(await screen.findByText("3.080 nm")).toBeVisible();
    expect(
      screen.getByRole("img", { name: /Interface profile with fitted curve/ }),
    ).toBeVisible();
    expect(screen.getByText(/amplitude 20.00/)).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    fireEvent.click(screen.getByRole("button", { name: "Export JSON" }));
    expect(downloadCsv).toHaveBeenCalledOnce();
    expect(downloadJson).toHaveBeenCalledOnce();
  });

  it("marks a retained fit stale when its model changes", async () => {
    vi.mocked(analyzeInterfaceWidth).mockResolvedValue(result);
    useStageInfo.getState().setProfile({
      dist: [0, 1, 2, 3],
      intensity: [0, 1, 2, 3],
      length: 3,
      unit: "px",
      reduce: "mean",
      measureId: "m1",
    });
    render(<InterfaceWidthWorkshop />);
    fireEvent.click(screen.getByRole("button", { name: "Fit profile" }));
    await screen.findByText("3.080 px");
    fireEvent.change(screen.getByLabelText("Model"), {
      target: { value: "sigmoid" },
    });
    expect(screen.getByRole("status")).toHaveTextContent("rerun");
  });

  it("exports all fitted scalars and units", () => {
    const run: FitRun = {
      result,
      sourceName: "interface.dm4",
      unit: "nm",
      x: [0, 10],
      y: [4, 24],
    };
    expect(interfaceWidthRows(run)).toEqual([
      ["center", 5, "nm"],
      ["sigma", 1.2, "nm"],
      ["width_10_90", 3.08, "nm"],
      ["amplitude", 20, "intensity"],
      ["offset", 4, "intensity"],
      ["r_squared", 0.992, ""],
      ["model", "erf", ""],
    ]);
  });
});
