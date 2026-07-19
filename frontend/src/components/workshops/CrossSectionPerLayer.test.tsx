import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  GrainLayersResult, GrainResult, ImageMeta, LayersResult,
} from "../../lib/api";
import { useCrossSection } from "../../store/crossSection";
import { useViewer } from "../../store/viewer";

vi.mock("../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/api")>();
  return { ...actual, analyzeGrainsByLayer: vi.fn() };
});

import { analyzeGrainsByLayer } from "../../lib/api";
import CrossSectionPerLayer from "./CrossSectionPerLayer";

const image = {
  id: "src", name: "film.dm4", kind: "image", shape: [100, 200],
  dtype: "float32", pixel_size: 0.5, pixel_unit: "nm", value_unit: "",
  n_channels: null, energy_first: null, energy_last: null, energy_units: "",
  stage_tilt_deg: null, meta: {},
} satisfies ImageMeta;

const layerResult = {
  axis: "y", unit: "nm", interfaces: [{ trace: null }, { trace: null }, { trace: null }],
  layers: [
    { index: 0, top: 0, bottom: 20, thickness: 10 },
    { index: 1, top: 20, bottom: 60, thickness: 20 },
  ],
} as LayersResult;

const grainResult = {
  labels: { id: "labels" }, method: "gradient", n_grains: 4,
} as GrainResult;

const measured = {
  axis: "y", pixel_size: 0.5, unit: "nm",
  layers: [{
    index: 1, n_grains: 3, mean_lateral_width: 8.5, mean_depth_height: 12,
    density_per_mpx: 1200, density_per_unit2: 0.12,
    mean_aspect_ratio: 0.71, mean_shape_angle_deg: 6.2, cross_layer_grains: 1,
  }],
  assignment: { ...image, id: "assignment", name: "layer grains(film.dm4)" },
  limitations: [],
} as unknown as GrainLayersResult;

afterEach(() => {
  vi.clearAllMocks();
  useCrossSection.getState().clear();
  useViewer.setState({ images: {}, order: [], activeId: null, selected: [] });
});

describe("CrossSectionPerLayer", () => {
  it("selects film bands, measures them, and opens the assignment map", async () => {
    useViewer.getState().ingest([image]);
    vi.mocked(analyzeGrainsByLayer).mockResolvedValue(measured);
    const onSelected = vi.fn();
    const { rerender } = render(
      <CrossSectionPerLayer
        sourceId="src" roi={null}
        layers={{ sourceId: "src", regionLabel: "Whole image", roi: null, result: layerResult, qualityAccepted: true }}
        grains={{ sourceId: "src", regionLabel: "Whole image", roi: null, minArea: 25, result: grainResult, qualityAccepted: true }}
        selected={[0, 1]} onSelected={onSelected}
      />,
    );
    fireEvent.click(screen.getAllByRole("checkbox")[0]);
    expect(onSelected).toHaveBeenCalledWith([1]);

    rerender(
      <CrossSectionPerLayer
        sourceId="src" roi={null}
        layers={{ sourceId: "src", regionLabel: "Whole image", roi: null, result: layerResult, qualityAccepted: true }}
        grains={{ sourceId: "src", regionLabel: "Whole image", roi: null, minArea: 25, result: grainResult, qualityAccepted: true }}
        selected={[1]} onSelected={onSelected}
      />,
    );
    fireEvent.click(screen.getByText("Measure selected layers"));
    await waitFor(() => expect(analyzeGrainsByLayer).toHaveBeenCalledWith(
      "labels", layerResult, [1], null,
    ));
    expect(await screen.findByText("8.5 nm")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Show assignment map"));
    expect(useViewer.getState().activeId).toBe("assignment");
  });
});
