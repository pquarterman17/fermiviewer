import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { GrainResult, ImageMeta, LayersResult } from "../../lib/api";
import { useCrossSection } from "../../store/crossSection";
import { useViewer } from "../../store/viewer";

vi.mock("./LayersWorkshop", () => ({
  default: () => <div>Layer workflow</div>,
  LayerStack: () => <div>Layer stack</div>,
}));
vi.mock("./StructureWorkshop", () => ({
  GrainsMode: () => <div>Grain workflow</div>,
}));

import CrossSectionGuide from "./CrossSectionGuide";

const image = {
  id: "src", name: "film.dm4", kind: "image", shape: [100, 200],
  dtype: "float32", pixel_size: 0.5, pixel_unit: "nm", value_unit: "",
  n_channels: null, energy_first: null, energy_last: null, energy_units: "",
  stage_tilt_deg: null, meta: {},
} satisfies ImageMeta;

afterEach(() => {
  useCrossSection.getState().clear();
  useViewer.setState({ images: {}, order: [], activeId: null, selected: [] });
});

describe("CrossSectionGuide", () => {
  it("walks through region, layers, grains, and a combined summary", () => {
    useViewer.getState().ingest([image]);
    render(<CrossSectionGuide />);
    expect(screen.getByText(/Source: film.dm4/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Draw ROI"));
    expect(useViewer.getState().captureMode).toBe("roi");

    fireEvent.click(screen.getByRole("button", { name: /Layers/ }));
    expect(screen.getByText("Layer workflow")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Grains/ }));
    expect(screen.getByText("Grain workflow")).toBeInTheDocument();

    act(() => useCrossSection.setState({
      layers: {
        sourceId: "src", regionLabel: "Whole image", roi: null,
        result: {
          axis: "y", layers_horizontal: true, tilt_deg: 0, coherence: 0.9,
          pixel_size: 0.5, unit: "nm", depth_pos: [], depth_profile: [],
          interfaces: [], layers: [],
        } as LayersResult,
        qualityAccepted: true,
      },
      grains: {
        sourceId: "src", regionLabel: "Whole image", roi: null, minArea: 25,
        result: {
          n_grains: 2, method: "gradient", mean_diameter_px: 20,
          astm_grain_size: null, boundary_network_px: 10,
          n_triple_junctions: 0, areas_px: [1000, 1000],
          perimeters_px: [100, 100], eccentricity: [0.2, 0.3],
        } as GrainResult,
        qualityAccepted: false,
      },
    }));
    fireEvent.click(screen.getByRole("button", { name: /Report/ }));
    expect(screen.getByText("Export combined JSON report")).not.toBeDisabled();
    expect(screen.getByText("2", { selector: ".fvd-metric .v" })).toBeInTheDocument();
  });
});
