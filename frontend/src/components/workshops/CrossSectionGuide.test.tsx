import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { GrainLayersResult, GrainResult, ImageMeta, LayersResult } from "../../lib/api";
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

const layersResult = {
  axis: "y", layers_horizontal: true, tilt_deg: 0, applied_tilt_deg: null, sampled_fraction: 1, coherence: 0.9,
  pixel_size: 0.5, unit: "nm", depth_pos: [0, 1, 2], depth_profile: [10, 20, 30],
  interfaces: [], layers: [],
} as LayersResult;

const layersSnapshot = (accepted: boolean) => ({
  sourceId: "src", regionLabel: "Whole image", roi: null,
  result: layersResult, qualityAccepted: accepted,
});

const grainsSnapshot = (accepted: boolean) => ({
  sourceId: "src", regionLabel: "Whole image", roi: null, minArea: 25,
  result: {
    n_grains: 2, method: "gradient", mean_diameter_px: 20,
    astm_grain_size: null, boundary_network_px: 10,
    n_triple_junctions: 0, areas_px: [1000, 1000],
    perimeters_px: [100, 100], eccentricity: [0.2, 0.3],
  } as GrainResult,
  qualityAccepted: accepted,
});

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
          axis: "y", layers_horizontal: true, tilt_deg: 0, applied_tilt_deg: null, sampled_fraction: 1, coherence: 0.9,
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
      perLayer: {
        sourceId: "src", roi: null, selectedLayerIndices: [],
        result: {
          axis: "y", pixel_size: 0.5, unit: "nm", layers: [],
          assignment: { id: "assignment" }, limitations: [],
        } as unknown as GrainLayersResult,
      },
    }));
    fireEvent.click(screen.getByRole("button", { name: /Report/ }));
    expect(screen.getByText("Export combined JSON report")).not.toBeDisabled();
    expect(screen.getByText("2", { selector: ".fvd-metric .v" })).toBeInTheDocument();
  });
  // The shipped bug: with layers and grains both run but the OPTIONAL
  // per-layer grain step skipped, the export button was disabled -- and a
  // disabled button swallows the click, so the user saw nothing happen at
  // all. The existing walkthrough test above always set `perLayer`, which is
  // why it never caught this. `buildCrossSectionReport` handles a null
  // perLayer by design, so there was never a format reason to block.
  it("exports with the optional per-layer step skipped", () => {
    useViewer.getState().ingest([image]);
    render(<CrossSectionGuide />);
    act(() => useCrossSection.setState({
      layers: layersSnapshot(true),
      grains: grainsSnapshot(true),
      perLayer: null,
    }));
    fireEvent.click(screen.getByRole("button", { name: /Report/ }));
    expect(screen.getByText("Export combined JSON report")).not.toBeDisabled();
    // and the user is told what is missing rather than left guessing
    expect(screen.getByText(/No per-layer grain measurement yet/)).toBeInTheDocument();
  });

  // The gate that must SURVIVE the fix: a poor result still has to be
  // acknowledged in its own step. Removing perLayerPending must not have
  // taken this with it.
  it("still blocks export on an unacknowledged poor result", () => {
    useViewer.getState().ingest([image]);
    render(<CrossSectionGuide />);
    act(() => useCrossSection.setState({
      // zero interfaces rates "poor" in assessLayerQuality
      layers: layersSnapshot(false),
      grains: grainsSnapshot(true),
      perLayer: null,
    }));
    fireEvent.click(screen.getByRole("button", { name: /Report/ }));
    expect(screen.getByText("Export combined JSON report")).toBeDisabled();
  });

  it("offers the layer table and the profile it was measured from", () => {
    useViewer.getState().ingest([image]);
    render(<CrossSectionGuide />);
    act(() => useCrossSection.setState({
      layers: layersSnapshot(true), grains: null, perLayer: null,
    }));
    fireEvent.click(screen.getByRole("button", { name: /Report/ }));
    expect(screen.getByText("Export layers CSV")).not.toBeDisabled();
    expect(screen.getByText("Export profile CSV")).not.toBeDisabled();
  });
});
