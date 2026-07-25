import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ImageMeta } from "../../lib/api";
import { useViewer } from "../../store/viewer";
import { useWorkshop } from "../../store/workshop";

vi.mock("../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/api")>();
  return {
    ...actual,
    analyzeLattice: vi.fn(),
    imageFft: vi.fn(),
  };
});

import { analyzeLattice, imageFft } from "../../lib/api";
import StructureWorkshop from "./StructureWorkshop";

function imageMeta(id: string, name = id): ImageMeta {
  return {
    id,
    name,
    kind: "image",
    shape: [64, 96],
    dtype: "float32",
    pixel_size: 0.5,
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

afterEach(() => {
  vi.clearAllMocks();
  useViewer.setState({
    images: {},
    order: [],
    activeId: null,
    selected: [],
    savedRois: {},
  });
  useWorkshop.setState({ structureMode: "Atoms" });
});

describe("StructureWorkshop lattice mode", () => {
  it("picks spots on an FFT preview but analyzes the calibrated source", async () => {
    const source = imageMeta("source");
    const fft = imageMeta("fft-preview", "FFT(source)");
    vi.mocked(imageFft).mockResolvedValue(fft);
    vi.mocked(analyzeLattice).mockResolvedValue({
      a: 4,
      b: 3.2,
      gamma_deg: 90,
      d_spacing1: 4,
      d_spacing2: 3.2,
      unit_cell_area: 12.8,
      unit: "nm",
    });
    useViewer.getState().ingest([source]);
    useViewer.getState().setActive(source.id);
    useWorkshop.getState().setStructureMode("Lattice");

    const { container } = render(<StructureWorkshop />);

    await waitFor(() => expect(imageFft).toHaveBeenCalledWith("source"));
    const previewImage = container.querySelector<HTMLImageElement>(
      'img[src*="/api/image/fft-preview/render"]',
    );
    expect(previewImage).not.toBeNull();
    Object.defineProperties(previewImage!, {
      naturalWidth: { configurable: true, value: 96 },
      naturalHeight: { configurable: true, value: 64 },
    });
    fireEvent.load(previewImage!);

    const preview = previewImage!.parentElement!;
    vi.spyOn(preview, "getBoundingClientRect").mockReturnValue({
      x: 0,
      y: 0,
      left: 0,
      top: 0,
      right: 300,
      bottom: 200,
      width: 300,
      height: 200,
      toJSON: () => ({}),
    });
    fireEvent.click(preview, { clientX: 190, clientY: 100 });
    fireEvent.click(preview, { clientX: 150, clientY: 130 });

    await waitFor(() =>
      expect(analyzeLattice).toHaveBeenCalledWith(
        "source",
        expect.any(Array),
        expect.any(Array),
      ),
    );
    expect(analyzeLattice).not.toHaveBeenCalledWith(
      "fft-preview",
      expect.anything(),
      expect.anything(),
    );
    expect((await screen.findAllByText("4.000 nm")).length).toBeGreaterThan(0);
  });
});
