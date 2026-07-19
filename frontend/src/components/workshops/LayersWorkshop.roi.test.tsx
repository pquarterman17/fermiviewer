import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ImageMeta, LayersResult } from "../../lib/api";
import { useViewer } from "../../store/viewer";

vi.mock("../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/api")>();
  return { ...actual, analyzeLayers: vi.fn() };
});

import { analyzeLayers } from "../../lib/api";
import LayersWorkshop from "./LayersWorkshop";

const image: ImageMeta = {
  id: "src", name: "cross section", kind: "image", shape: [100, 200],
  dtype: "float32", pixel_size: null, pixel_unit: "px", value_unit: "",
  n_channels: null, energy_first: null, energy_last: null, energy_units: "",
  stage_tilt_deg: null, meta: {},
};

const result: LayersResult = {
  axis: "y", layers_horizontal: true, tilt_deg: 0, coherence: 0.1,
  pixel_size: 1, unit: "px", depth_pos: [], depth_profile: [],
  interfaces: [{
    position: 20, sigma_erf: 1, r_squared: 0.9, sigma_w: null,
    trace: null, roughness: null,
  }],
  layers: [{
    index: 0, top: 0, bottom: 20, thickness: 20,
    thickness_std: null, conformality: null,
  }],
};

afterEach(() => {
  vi.clearAllMocks();
  useViewer.setState({
    images: {}, order: [], activeId: null, selected: [], savedRois: {},
    layersOverlay: null,
  });
});

describe("LayersWorkshop ROI", () => {
  it("passes the selected named ROI to layer detection", async () => {
    useViewer.getState().ingest([image]);
    useViewer.setState({
      savedRois: {
        src: [{
          id: "film", name: "Film only", kind: "roi",
          pts: [{ x: 0.1, y: 0.2 }, { x: 0.9, y: 0.8 }],
          createdAt: "2026-07-19T00:00:00Z",
        }],
      },
    });
    vi.mocked(analyzeLayers).mockResolvedValue(result);

    render(<LayersWorkshop />);
    fireEvent.change(screen.getByLabelText("Region"), {
      target: { value: "saved:film" },
    });
    fireEvent.click(screen.getByText("Analyze"));

    await waitFor(() => expect(analyzeLayers).toHaveBeenCalledWith(
      "src",
      expect.objectContaining({ roi: [21, 21, 80, 180] }),
    ));
    expect(screen.getByText("Export CSV")).toBeDisabled();
    fireEvent.click(screen.getByText("Use anyway"));
    expect(screen.getByText("Export CSV")).not.toBeDisabled();
  });
});
