import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  ImageMeta,
  LayersMultiResult,
} from "../../lib/api";
import { useViewer } from "../../store/viewer";

vi.mock("../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/api")>();
  return { ...actual, analyzeLayersMulti: vi.fn() };
});

vi.mock("../../lib/resultsExport", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/resultsExport")>();
  return {
    ...actual,
    downloadCsv: vi.fn(),
    downloadJson: vi.fn(),
  };
});

import { analyzeLayersMulti } from "../../lib/api";
import { downloadCsv, downloadJson } from "../../lib/resultsExport";
import LayersMultiCompare, {
  mapCompatibility,
  multiMapTable,
} from "./LayersMultiCompare";

function image(
  id: string,
  pixelSize = 0.5,
  shape = [120, 80],
): ImageMeta {
  return {
    id,
    name: `${id}.dm4`,
    kind: "image",
    shape,
    dtype: "float32",
    pixel_size: pixelSize,
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

const images = {
  reference: image("reference"),
  diffuse: image("diffuse"),
  incompatible: image("incompatible", 1),
};

const result: LayersMultiResult = {
  axis: "y",
  unit: "nm",
  reference_id: "reference",
  reference_positions: [30, 70],
  roi: [11, 1, 110, 80],
  maps: [
    {
      image_id: "reference",
      name: "reference.dm4",
      interfaces: [
        { position: 30, sigma_erf: 1, sigma_w: 0.4 },
        { position: 70, sigma_erf: 1.2, sigma_w: 0.5 },
      ],
      layers: [{ index: 0, thickness: 20, thickness_std: 1 }],
    },
    {
      image_id: "diffuse",
      name: "diffuse.dm4",
      interfaces: [
        { position: 30, sigma_erf: 2.5, sigma_w: 0.6 },
        { position: 70, sigma_erf: 2.8, sigma_w: 0.7 },
      ],
      layers: [{ index: 0, thickness: 20.2, thickness_std: 1.1 }],
    },
  ],
};

afterEach(() => {
  vi.clearAllMocks();
  useViewer.setState({ status: "" });
});

describe("LayersMultiCompare", () => {
  it("disables incompatible maps and submits all comparison controls", async () => {
    vi.mocked(analyzeLayersMulti).mockResolvedValue(result);
    render(
      <LayersMultiCompare
        activeId="reference"
        mapIds={Object.keys(images)}
        images={images}
        roi={[11, 1, 110, 80]}
        regionLabel="Film only"
      />,
    );

    expect(screen.getByLabelText(/incompatible\.dm4/)).toBeDisabled();
    fireEvent.click(screen.getByLabelText("diffuse.dm4"));
    fireEvent.change(screen.getByLabelText("Axis"), { target: { value: "y" } });
    fireEvent.change(screen.getByLabelText("Sensitivity"), {
      target: { value: "0.2" },
    });
    fireEvent.change(screen.getByLabelText("# layers"), {
      target: { value: "3" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Compare 2 maps" }));

    await waitFor(() =>
      expect(analyzeLayersMulti).toHaveBeenCalledWith(
        ["reference", "diffuse"],
        {
          reference: 0,
          roi: [11, 1, 110, 80],
          axis: "y",
          sensitivity: 0.2,
          nLayers: 3,
          modality: "haadf",
          waviness: true,
        },
      ),
    );
    expect(
      await screen.findByRole("img", {
        name: "Interface width σ_erf across maps and interfaces",
      }),
    ).toBeVisible();
    expect(screen.getByText(/positions are not independently detected/)).toBeVisible();
    expect(screen.getByText("2.5")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    fireEvent.click(screen.getByRole("button", { name: "Export JSON" }));
    expect(downloadCsv).toHaveBeenCalledOnce();
    expect(downloadJson).toHaveBeenCalledOnce();
  });

  it("reports the specific compatibility mismatch", () => {
    expect(mapCompatibility(images.reference, images.diffuse)).toBeNull();
    expect(mapCompatibility(images.reference, images.incompatible)).toMatch(
      /calibration/,
    );
    expect(
      mapCompatibility(images.reference, image("small", 0.5, [20, 20])),
    ).toMatch(/shape/);
  });

  it("keeps every interface and layer value in the export matrix", () => {
    expect(multiMapTable(result)).toEqual({
      columns: [
        "map",
        "interface_1_sigma_erf_nm",
        "interface_1_sigma_w_nm",
        "interface_2_sigma_erf_nm",
        "interface_2_sigma_w_nm",
        "layer_1_thickness_nm",
      ],
      rows: [
        ["reference.dm4", 1, 0.4, 1.2, 0.5, 20],
        ["diffuse.dm4", 2.5, 0.6, 2.8, 0.7, 20.2],
      ],
    });
  });
});
