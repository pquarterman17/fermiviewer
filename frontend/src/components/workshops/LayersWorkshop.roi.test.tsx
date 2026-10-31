import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ImageMeta, LayersResult } from "../../lib/api";
import { useCrossSection } from "../../store/crossSection";
import { useViewer } from "../../store/viewer";
import { useWorkshop } from "../../store/workshop";

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
  axis: "y", layers_horizontal: true, tilt_deg: 0, applied_tilt_deg: null, sampled_fraction: 1, coherence: 0.1,
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

function deferredLayers() {
  let resolve!: (value: LayersResult) => void;
  vi.mocked(analyzeLayers).mockReturnValue(
    new Promise((next) => { resolve = next; }),
  );
  return (value: LayersResult) => resolve(value);
}

afterEach(() => {
  vi.clearAllMocks();
  useCrossSection.getState().clear();
  useViewer.setState({
    images: {}, order: [], activeId: null, selected: [], savedRois: {},
    layersOverlay: null,
  });
});

describe("LayersWorkshop ROI", () => {
  it("promotes multi-map analysis to a dedicated comparison mode", () => {
    useViewer.getState().ingest([image]);
    render(<LayersWorkshop />);
    fireEvent.click(screen.getByRole("button", { name: "Compare maps" }));
    expect(screen.getByLabelText("Reference")).toBeVisible();
    expect(screen.getByText(/Detect interfaces once on a reference/)).toBeVisible();
  });

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
    // The click event must not leak into the tilt argument (it used to,
    // and JSON-serialising the event aborted every run).
    expect(vi.mocked(analyzeLayers).mock.calls[0]?.[1]?.tiltDeg).toBeNull();
    expect(screen.getByText("Export CSV")).toBeDisabled();
    fireEvent.click(screen.getByText("Use anyway"));
    expect(screen.getByText("Export CSV")).not.toBeDisabled();
  });

  it("drops a layer analysis that lands after the image changes", async () => {
    const resolve = deferredLayers();
    useViewer.getState().ingest([image, { ...image, id: "other", name: "other" }]);
    useViewer.getState().setActive("src");
    render(<LayersWorkshop />);

    fireEvent.click(screen.getByText("Analyze"));
    const signal = vi.mocked(analyzeLayers).mock.calls[0]![1]!.signal!;
    act(() => useViewer.getState().setActive("other"));
    await act(async () => resolve(result));

    expect(signal.aborted).toBe(true);
    expect(screen.queryByText("Export CSV")).toBeNull();
    expect(useViewer.getState().layersOverlay).toBeNull();
    expect(useCrossSection.getState().layers).toBeNull();
    expect(screen.getByText("Analyze")).not.toBeDisabled();
  });

  it("drops a whole-image analysis that lands after the region changes", async () => {
    const resolve = deferredLayers();
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
    useWorkshop.getState().setAnalysisRegionChoice("src", "whole");
    render(<LayersWorkshop />);

    fireEvent.click(screen.getByText("Analyze"));
    expect(vi.mocked(analyzeLayers).mock.calls[0]![1]!.roi).toBeNull();
    act(() => useWorkshop.getState().setAnalysisRegionChoice("src", "saved:film"));
    await act(async () => resolve(result));

    expect(screen.queryByText("Export CSV")).toBeNull();
    expect(useCrossSection.getState().layers).toBeNull();
    expect(screen.getByText("Analyze")).not.toBeDisabled();
  });
});
