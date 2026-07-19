// Trained-grains flow integration (regression for the reset-effect race):
// trainRun() sets the produced grain map as the active image so the stage
// merge/split editor can act on it — which changes GrainsMode's `id` prop.
// The [id] reset effect must NOT treat that self-initiated switch as a user
// image change, or it wipes the just-computed result (metric tiles, merge/
// split note, CSV/PNG buttons) on the very next commit.

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { GrainResult, ImageMeta } from "../../lib/api";
import { recordCrossSectionGrains, useCrossSection } from "../../store/crossSection";
import { useScribble } from "../../store/scribble";
import { useViewer } from "../../store/viewer";
import { useWorkshop } from "../../store/workshop";

vi.mock("../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/api")>();
  return {
    ...actual,
    analyzeGrainsAsync: vi.fn(),
    grainsTrainSegment: vi.fn(),
    runJob: vi.fn(),
  };
});

import { analyzeGrainsAsync, grainsTrainSegment, runJob } from "../../lib/api";
import StructureWorkshop, { GrainsMode } from "./StructureWorkshop";

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
  useViewer.setState({
    images: {}, order: [], activeId: null, selected: [], savedRois: {},
  });
  useWorkshop.setState({ structureMode: "Atoms" });
  useCrossSection.getState().clear();
});

describe("StructureWorkshop trained flow", () => {
  it("restores a reviewed result when the guided workflow revisits the step", () => {
    const result = grainResult("grains-restored");
    useViewer.getState().ingest([imageMeta("src"), result.labels]);
    useViewer.getState().setActive("src");
    recordCrossSectionGrains("src", "Whole image", null, 25, result);

    const first = render(<GrainsMode id="src" />);
    expect(screen.getByText("34")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Use anyway"));
    expect(screen.getByText("CSV")).not.toBeDisabled();
    first.unmount();

    render(<GrainsMode id="src" />);
    expect(screen.getByText("34")).toBeInTheDocument();
    expect(screen.queryByText("Use anyway")).toBeNull();
    expect(screen.getByText("CSV")).not.toBeDisabled();
  });

  it("keeps the result after training swaps the active image to the grain map", async () => {
    useViewer.getState().ingest([imageMeta("src")]);
    useViewer.getState().setActive("src");
    vi.mocked(grainsTrainSegment).mockResolvedValue(grainResult("grains1"));

    render(<StructureWorkshop />);
    fireEvent.click(screen.getByText("Grains"));
    // switch method → "trained" (this arms the paint overlay, clearing strokes)
    fireEvent.change(screen.getByRole("combobox", { name: "Grain method" }), {
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
    expect(grainsTrainSegment).toHaveBeenCalledWith(
      "src",
      expect.any(Array),
      expect.any(Object),
    );
    // the metric tiles, merge/split note, and export buttons all survive
    expect(screen.getByText("grains")).toBeInTheDocument();
    expect(screen.getByText(/merge/)).toBeInTheDocument();
    expect(screen.getByText("CSV")).toBeDisabled();
    expect(screen.getByText("Overlay PNG")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Use anyway"));
    expect(screen.getByText("CSV")).not.toBeDisabled();
    // and the active image is the produced grain map
    expect(useViewer.getState().activeId).toBe("grains1");

    // a GENUINE user switch to a different image still clears the stale result
    // (the guard only exempts training's own self-initiated switch)
    act(() => {
      useViewer.getState().ingest([imageMeta("other")]);
    });
    await waitFor(() => expect(screen.queryByText("34")).toBeNull());
  });

  it("reruns a classic method against the original source, not its label map", async () => {
    // classic methods never call setActive, but ingestDerived([labels]) makes
    // the derived grain map active via _ingest — the same reset race
    useViewer.getState().ingest([imageMeta("src")]);
    useViewer.getState().setActive("src");
    vi.mocked(runJob)
      .mockResolvedValueOnce(grainResult("grains2"))
      .mockResolvedValueOnce(grainResult("grains3"));

    render(<StructureWorkshop />);
    fireEvent.click(screen.getByText("Grains"));
    // default method is "gradient" → the classic "Identify grains" button
    fireEvent.click(screen.getByText("Identify grains"));

    await waitFor(() => expect(screen.getByText("34")).toBeInTheDocument());
    expect(runJob).toHaveBeenCalledOnce();
    expect(screen.getByText("Source image: src")).toBeInTheDocument();
    expect(screen.getByText("junctions")).toBeInTheDocument();
    expect(screen.getByText("CSV")).toBeInTheDocument();
    expect(useViewer.getState().activeId).toBe("grains2");

    // runJob receives a deferred submitter. Execute each one just far enough
    // to assert which image id the API would receive.
    vi.mocked(runJob).mock.calls[0][0]();
    expect(analyzeGrainsAsync).toHaveBeenLastCalledWith(
      "src",
      expect.any(Object),
    );

    // The active id is now the first label map. Retrying must still submit the
    // original source and may replace the current result without resetting it.
    fireEvent.click(screen.getByText("Identify grains"));
    await waitFor(() => expect(runJob).toHaveBeenCalledTimes(2));
    vi.mocked(runJob).mock.calls[1][0]();
    expect(analyzeGrainsAsync).toHaveBeenLastCalledWith(
      "src",
      expect.any(Object),
    );
    await waitFor(() => expect(useViewer.getState().activeId).toBe("grains3"));
  });

  it("submits a named ROI in backend coordinates", async () => {
    useViewer.getState().ingest([imageMeta("src")]);
    useViewer.setState({
      savedRois: {
        src: [{
          id: "film",
          name: "Film only",
          kind: "roi",
          pts: [{ x: 0.25, y: 0.125 }, { x: 0.75, y: 0.875 }],
          createdAt: "2026-07-19T00:00:00Z",
        }],
      },
    });
    vi.mocked(runJob).mockResolvedValue(grainResult("grains-roi"));

    render(<StructureWorkshop />);
    fireEvent.click(screen.getByText("Grains"));
    fireEvent.change(screen.getByLabelText("Region"), {
      target: { value: "saved:film" },
    });
    fireEvent.click(screen.getByText("Identify grains"));
    await waitFor(() => expect(runJob).toHaveBeenCalledOnce());
    vi.mocked(runJob).mock.calls[0][0]();

    expect(analyzeGrainsAsync).toHaveBeenCalledWith(
      "src",
      expect.objectContaining({ roi: [9, 17, 56, 48] }),
    );
  });
});
