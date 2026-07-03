// Trained-grains flow integration (regression for the reset-effect race):
// trainRun() sets the produced grain map as the active image so the stage
// merge/split editor can act on it — which changes GrainsMode's `id` prop.
// The [id] reset effect must NOT treat that self-initiated switch as a user
// image change, or it wipes the just-computed result (metric tiles, merge/
// split note, CSV/PNG buttons) on the very next commit.

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { GrainResult, ImageMeta } from "../../lib/api";
import { useScribble } from "../../store/scribble";
import { useViewer } from "../../store/viewer";

vi.mock("../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/api")>();
  return { ...actual, grainsTrainSegment: vi.fn(), runJob: vi.fn() };
});

import { grainsTrainSegment, runJob } from "../../lib/api";
import StructureWorkshop from "./StructureWorkshop";

function imageMeta(id: string, extra: Partial<ImageMeta> = {}): ImageMeta {
  return {
    id,
    name: id,
    kind: "image",
    shape: [64, 64],
    dtype: "float32",
    pixel_size: null,
    pixel_unit: "px",
    value_unit: "",
    n_channels: null,
    energy_first: null,
    energy_last: null,
    energy_units: "",
    stage_tilt_deg: null,
    meta: {},
    ...extra,
  };
}

function grainResult(labelsId: string): GrainResult {
  return {
    n_grains: 34,
    method: "trained",
    labels: imageMeta(labelsId, {
      name: "grains(src)",
      meta: { grain_labels: true, grain_source: "src" },
    }),
    mean_diameter_px: 12.4,
    boundary_length_px: 0,
    boundary_network_px: 0,
    boundary_length_calibrated: null,
    n_boundary_segments: 0,
    n_triple_junctions: 41,
    astm_grain_size: 7.4,
    areas_px: [100, 90],
    perimeters_px: [40, 38],
    eccentricity: [0.3, 0.4],
    unit: "px",
  };
}

afterEach(() => {
  vi.clearAllMocks();
  useScribble.getState().end();
  useViewer.setState({ images: {}, order: [], activeId: null, selected: [] });
});

describe("StructureWorkshop trained flow", () => {
  it("keeps the result after training swaps the active image to the grain map", async () => {
    useViewer.getState().ingest([imageMeta("src")]);
    useViewer.getState().setActive("src");
    vi.mocked(grainsTrainSegment).mockResolvedValue(grainResult("grains1"));

    render(<StructureWorkshop />);
    fireEvent.click(screen.getByText("Grains"));
    // switch method → "trained" (this arms the paint overlay, clearing strokes)
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "trained" },
    });
    // paint two classes, then the "Train & segment" button enables
    act(() => {
      useScribble.setState({
        strokes: [
          { classId: 1, radius: 4, points: [[10, 10]] },
          { classId: 2, radius: 4, points: [[50, 50]] },
        ],
      });
    });
    const trainBtn = screen.getByText("Train & segment");
    await waitFor(() => expect(trainBtn).not.toBeDisabled());
    fireEvent.click(trainBtn);

    // training completes → active image becomes the grain map (id changes),
    // but the result must remain on screen
    await waitFor(() =>
      expect(screen.getByText("34")).toBeInTheDocument(),
    );
    expect(grainsTrainSegment).toHaveBeenCalledOnce();
    // the metric tiles, merge/split note, and export buttons all survive
    expect(screen.getByText("grains")).toBeInTheDocument();
    expect(screen.getByText(/merge/)).toBeInTheDocument();
    expect(screen.getByText("CSV")).toBeInTheDocument();
    expect(screen.getByText("Overlay PNG")).toBeInTheDocument();
    // and the active image is the produced grain map
    expect(useViewer.getState().activeId).toBe("grains1");

    // a GENUINE user switch to a different image still clears the stale result
    // (the guard only exempts training's own self-initiated switch)
    act(() => {
      useViewer.getState().ingest([imageMeta("other")]);
    });
    await waitFor(() => expect(screen.queryByText("34")).toBeNull());
  });

  it("keeps the result after a classic method makes the grain map active", async () => {
    // classic methods never call setActive, but ingestDerived([labels]) makes
    // the derived grain map active via _ingest — the same reset race
    useViewer.getState().ingest([imageMeta("src")]);
    useViewer.getState().setActive("src");
    vi.mocked(runJob).mockResolvedValue(grainResult("grains2"));

    render(<StructureWorkshop />);
    fireEvent.click(screen.getByText("Grains"));
    // default method is "gradient" → the classic "Identify grains" button
    fireEvent.click(screen.getByText("Identify grains"));

    await waitFor(() => expect(screen.getByText("34")).toBeInTheDocument());
    expect(runJob).toHaveBeenCalledOnce();
    expect(screen.getByText("junctions")).toBeInTheDocument();
    expect(screen.getByText("CSV")).toBeInTheDocument();
    expect(useViewer.getState().activeId).toBe("grains2");
  });
});
