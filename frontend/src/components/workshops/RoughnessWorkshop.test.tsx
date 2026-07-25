import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ImageMeta, RoughnessResult } from "../../lib/api";
import { useViewer } from "../../store/viewer";

vi.mock("uplot", () => ({
  default: class {
    destroy() {}
  },
}));

vi.mock("../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/api")>();
  return { ...actual, analyzeRoughness: vi.fn() };
});

vi.mock("../../lib/resultsExport", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/resultsExport")>();
  return {
    ...actual,
    downloadCsv: vi.fn(),
    downloadJson: vi.fn(),
  };
});

import { analyzeRoughness } from "../../lib/api";
import { downloadCsv, downloadJson } from "../../lib/resultsExport";
import RoughnessWorkshop, { roughnessRows } from "./RoughnessWorkshop";

const result: RoughnessResult = {
  Ra: 1.25,
  Rq: 1.5,
  Rz: 7.5,
  Rsk: 0.1,
  Rku: 3.1,
  Rp: 4,
  Rv: 3.5,
  SAR: 1.02,
  unit: "nm",
  n_pixels: 4096,
  level: "plane",
  roi: null,
  bearing_fraction: [0.1, 0.5, 1],
  bearing_heights: [3, 0, -3],
};

function imageMeta(): ImageMeta {
  return {
    id: "surface",
    name: "surface.dm4",
    kind: "image",
    shape: [64, 64],
    dtype: "float32",
    pixel_size: 0.5,
    pixel_unit: "nm",
    value_unit: "nm",
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
  useViewer.setState({
    images: {},
    order: [],
    activeId: null,
    selected: [],
    savedRois: {},
    measures: {},
  });
});

describe("RoughnessWorkshop", () => {
  it("runs a leveled regional analysis and keeps rich results visible", async () => {
    vi.mocked(analyzeRoughness).mockResolvedValue(result);
    useViewer.getState().ingest([imageMeta()]);
    useViewer.getState().setActive("surface");

    render(<RoughnessWorkshop />);
    fireEvent.click(screen.getByRole("button", { name: "Analyze" }));

    await waitFor(() =>
      expect(analyzeRoughness).toHaveBeenCalledWith("surface", {
        level: "plane",
        roi: null,
      }),
    );
    expect(await screen.findByText("1.250 nm")).toBeVisible();
    expect(screen.getByText("Material ratio / bearing curve")).toBeVisible();
    expect(screen.getByText(/4,096 valid pixels/)).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    fireEvent.click(screen.getByRole("button", { name: "Export JSON" }));
    expect(downloadCsv).toHaveBeenCalledOnce();
    expect(downloadJson).toHaveBeenCalledOnce();
  });

  it("exports every visible metric with its unit", () => {
    expect(roughnessRows(result)).toEqual([
      ["Ra", 1.25, "nm"],
      ["Rq", 1.5, "nm"],
      ["Rz", 7.5, "nm"],
      ["Rp", 4, "nm"],
      ["Rv", 3.5, "nm"],
      ["Rsk", 0.1, ""],
      ["Rku", 3.1, ""],
      ["SAR", 1.02, ""],
    ]);
  });
});
