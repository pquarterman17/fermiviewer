import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ImageMeta, LayersResult } from "../../../lib/api";
import { useViewer } from "../../../store/viewer";

vi.mock("../../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../../lib/api")>();
  return { ...actual, exportImage: vi.fn() };
});

import { exportImage } from "../../../lib/api";
import { LayersExportRow } from "./LayersExportRow";

const meta = (id: string): ImageMeta => ({
  id, name: id, kind: "image", shape: [100, 200],
  dtype: "float32", pixel_size: null, pixel_unit: "px", value_unit: "",
  n_channels: null, energy_first: null, energy_last: null, energy_units: "",
  stage_tilt_deg: null, meta: {},
});

const result = {
  unit: "nm",
  layers: [
    { index: 0, top: 20, bottom: 60, thickness: 40, thickness_std: null },
  ],
} as unknown as LayersResult;

beforeEach(() => {
  vi.mocked(exportImage).mockResolvedValue({
    blob: new Blob(["x"]), filename: "figure.png",
  });
  URL.createObjectURL = vi.fn(() => "blob:fig");
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  vi.clearAllMocks();
  useViewer.setState({ images: {}, order: [], activeId: null, layersOverlay: null });
});

function mount(roi: [number, number, number, number] | null = null) {
  useViewer.getState().ingest([meta("src"), meta("other")]);
  useViewer.setState({
    activeId: "other",
    layersOverlay: {
      imageId: "src",
      axis: "y",
      interfaces: [20, 60],
      traces: [null, null],
      lateralRange: [0, 200],
      tiltDeg: 0,
    },
  });
  render(
    <LayersExportRow
      result={result}
      roi={roi}
      disabled={false}
      saveResult={false}
      onSaveResult={() => {}}
      onError={() => {}}
    />,
  );
}

describe("LayersExportRow figure export", () => {
  it("renders the image the stack was measured on, not the active one", async () => {
    // the overlay carries its own imageId; exporting the active image
    // would draw one specimen's interfaces over another
    mount();
    fireEvent.click(screen.getByText("Export figure"));
    await waitFor(() => expect(exportImage).toHaveBeenCalled());
    expect(vi.mocked(exportImage).mock.calls[0][0]).toBe("src");
  });

  it("burns in one line per interface, labelled with the layer thickness", async () => {
    mount();
    fireEvent.click(screen.getByText("Export figure"));
    await waitFor(() => expect(exportImage).toHaveBeenCalled());
    const opts = vi.mocked(exportImage).mock.calls[0][1];
    expect(opts.include).toContain("measurements");
    const lines = (opts.measures ?? []).filter((m) => m.kind === "line");
    expect(lines).toHaveLength(2);
    // interface at row 20 of a 100-row image
    expect(lines[0].pts[0].y).toBeCloseTo(0.2, 6);
    expect(lines[0].text).toBe("40 nm");
  });

  it("marks the analysed region so the figure says what was measured", async () => {
    mount([11, 21, 60, 80]);
    fireEvent.click(screen.getByText("Export figure"));
    await waitFor(() => expect(exportImage).toHaveBeenCalled());
    const opts = vi.mocked(exportImage).mock.calls[0][1];
    expect((opts.measures ?? []).some((m) => m.kind === "box")).toBe(true);
  });
});
