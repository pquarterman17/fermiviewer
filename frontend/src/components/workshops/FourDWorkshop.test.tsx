import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/api")>();
  return {
    ...actual,
    listFourD: vi.fn(),
    fetchFourDNav: vi.fn(),
    fetchFourDMeanPattern: vi.fn(),
    fetchFourDPattern: vi.fn(),
    fetchData16: vi.fn(),
    computeVirtualDetector: vi.fn(),
    closeFourD: vi.fn(),
  };
});

import type { FourDMeta, ImageMeta, Raster16 } from "../../lib/api";
import {
  closeFourD,
  computeVirtualDetector,
  fetchData16,
  fetchFourDMeanPattern,
  fetchFourDNav,
  fetchFourDPattern,
  listFourD,
} from "../../lib/api";
import { useFourD } from "../../store/fourd";
import { useViewer } from "../../store/viewer";
import FourDWorkshop from "./FourDWorkshop";

function fourdMeta(): FourDMeta {
  return {
    id: "d1",
    name: "synthetic.mib",
    is_fourd: true,
    source: "/data/synthetic.mib",
    scan_shape: [4, 5],
    det_shape: [64, 64],
    dtype: "uint16",
    scan_axes: [
      { scale: 1, origin: 0, units: "nm" },
      { scale: 1, origin: 0, units: "nm" },
    ],
    det_axes: [
      { scale: 1, origin: 0, units: "" },
      { scale: 1, origin: 0, units: "" },
    ],
    nav_available: true,
  n_frames: 0,
  scan_shape_from_file: true,
  scan_shape_options: [],
  };
}

function raster(w = 4, h = 5): Raster16 {
  return { data: new Uint16Array(w * h).fill(100), w, h, vmin: 0, vmax: 65535, nFrames: null };
}

function imageMeta(id: string): ImageMeta {
  return {
    id,
    name: id,
    kind: "image",
    shape: [4, 5],
    dtype: "float64",
    pixel_size: null,
    pixel_unit: "",
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
  useFourD.getState().reset();
  useViewer.setState({ images: {}, order: [], activeId: null });
});

describe("FourDWorkshop", () => {
  it("shows an empty-state hint when no 4D datasets are open", async () => {
    vi.mocked(listFourD).mockResolvedValue([]);
    render(<FourDWorkshop />);
    expect(
      await screen.findByText("No 4D-STEM datasets are open."),
    ).toBeVisible();
    expect(screen.getByText(/\.mib.*Merlin/)).toBeVisible();
  });

  it("surfaces a dataset-list fetch failure instead of the generic empty hint", async () => {
    vi.mocked(listFourD).mockRejectedValue(new Error("network error"));
    render(<FourDWorkshop />);
    expect(
      await screen.findByText(/4D datasets: network error/),
    ).toBeVisible();
    expect(screen.queryByText("No 4D-STEM datasets are open.")).toBeNull();
  });

  it("lists datasets and loads the mean pattern + nav minimap on selection", async () => {
    vi.mocked(listFourD).mockResolvedValue([fourdMeta()]);
    vi.mocked(fetchFourDMeanPattern).mockResolvedValue(raster(64, 64));
    vi.mocked(fetchFourDNav).mockResolvedValue(imageMeta("nav1"));
    vi.mocked(fetchData16).mockResolvedValue(raster(5, 4));

    render(<FourDWorkshop />);
    const select = await screen.findByLabelText("4D-STEM dataset");
    fireEvent.change(select, { target: { value: "d1" } });

    await waitFor(() => expect(fetchFourDMeanPattern).toHaveBeenCalledWith("d1"));
    await waitFor(() => expect(fetchFourDNav).toHaveBeenCalledWith("d1"));
    // selecting a dataset alone must not surface the nav image on the main Stage
    expect(useViewer.getState().images.nav1).toBeUndefined();

    expect(await screen.findByText("mean pattern")).toBeVisible();
    expect(screen.getByRole("button", { name: "BF" })).toHaveClass("active");
  });

  it("clicking the nav minimap probes a scan position and fetches its pattern", async () => {
    vi.mocked(listFourD).mockResolvedValue([fourdMeta()]);
    vi.mocked(fetchFourDMeanPattern).mockResolvedValue(raster(64, 64));
    vi.mocked(fetchFourDNav).mockResolvedValue(imageMeta("nav1"));
    vi.mocked(fetchData16).mockResolvedValue(raster(5, 4));
    vi.mocked(fetchFourDPattern).mockResolvedValue(raster(64, 64));

    render(<FourDWorkshop />);
    fireEvent.change(await screen.findByLabelText("4D-STEM dataset"), {
      target: { value: "d1" },
    });
    await screen.findByText("mean pattern");

    const minimap = screen.getByRole("img", {
      name: "Navigation image — click or drag to probe a scan position",
    });
    vi.spyOn(minimap, "getBoundingClientRect").mockReturnValue({
      x: 0, y: 0, left: 0, top: 0, right: 180, bottom: 144,
      width: 180, height: 144, toJSON: () => ({}),
    });
    fireEvent.pointerDown(minimap, { clientX: 0, clientY: 0 });

    await waitFor(() =>
      expect(fetchFourDPattern).toHaveBeenCalledWith(
        "d1",
        0,
        0,
        { signal: expect.any(AbortSignal) },
      ),
    );
    // the nav minimap's own note is the exact short form (no calibrated
    // suffix) — the pattern panel's probeLabel adds "px = (…) nm" and is
    // covered separately by probeLabel's unit test
    expect(await screen.findByText("probe (0, 0)")).toBeVisible();
  });

  it("Compute map posts the exact virtual-detector contract and ingests the result", async () => {
    vi.mocked(listFourD).mockResolvedValue([fourdMeta()]);
    vi.mocked(fetchFourDMeanPattern).mockResolvedValue(raster(64, 64));
    vi.mocked(fetchFourDNav).mockResolvedValue(imageMeta("nav1"));
    vi.mocked(fetchData16).mockResolvedValue(raster(5, 4));
    vi.mocked(computeVirtualDetector).mockResolvedValue(imageMeta("map1"));

    render(<FourDWorkshop />);
    fireEvent.change(await screen.findByLabelText("4D-STEM dataset"), {
      target: { value: "d1" },
    });
    await screen.findByText("mean pattern");

    fireEvent.click(screen.getByRole("button", { name: "Compute map" }));

    await waitFor(() =>
      expect(computeVirtualDetector).toHaveBeenCalledWith("d1", {
        center_ky: null,
        center_kx: null,
        inner_r: 0,
        outer_r: 8, // BF preset: min(det_shape)=64 / 8
        shape: "circle",
        name: "bf(synthetic.mib)",
      }),
    );
    await waitFor(() => expect(useViewer.getState().images.map1).toBeDefined());
  });

  it("disables Close until a dataset is selected", async () => {
    vi.mocked(listFourD).mockResolvedValue([fourdMeta()]);
    vi.mocked(fetchFourDMeanPattern).mockResolvedValue(raster(64, 64));
    vi.mocked(fetchFourDNav).mockResolvedValue(imageMeta("nav1"));
    vi.mocked(fetchData16).mockResolvedValue(raster(5, 4));

    render(<FourDWorkshop />);
    await screen.findByLabelText("4D-STEM dataset");
    expect(screen.getByRole("button", { name: "Close" })).toBeDisabled();

    fireEvent.change(screen.getByLabelText("4D-STEM dataset"), {
      target: { value: "d1" },
    });
    await screen.findByText("mean pattern");
    expect(screen.getByRole("button", { name: "Close" })).toBeEnabled();
  });

  it("Close releases the dataset, refreshes the list, and clears the selection — without touching a derived nav image", async () => {
    vi.mocked(listFourD)
      .mockResolvedValueOnce([fourdMeta()])
      .mockResolvedValueOnce([]);
    vi.mocked(fetchFourDMeanPattern).mockResolvedValue(raster(64, 64));
    vi.mocked(fetchFourDNav).mockResolvedValue(imageMeta("nav1"));
    vi.mocked(fetchData16).mockResolvedValue(raster(5, 4));
    vi.mocked(closeFourD).mockResolvedValue(undefined);

    render(<FourDWorkshop />);
    fireEvent.change(await screen.findByLabelText("4D-STEM dataset"), {
      target: { value: "d1" },
    });
    await screen.findByText("mean pattern");
    // register the derived nav image in the main viewer store first, the
    // same way a real session would before closing the 4D dataset
    fireEvent.click(screen.getByRole("button", { name: "Show nav image" }));
    await waitFor(() => expect(useViewer.getState().images.nav1).toBeDefined());

    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    await waitFor(() => expect(closeFourD).toHaveBeenCalledWith("d1"));
    await waitFor(() => expect(listFourD).toHaveBeenCalledTimes(2));
    expect(
      await screen.findByText("No 4D-STEM datasets are open."),
    ).toBeVisible();
    // the workshop's own 4D state (mean pattern, nav minimap, aperture) is
    // gone, but the derived image in the main viewer store is untouched
    expect(screen.queryByText("mean pattern")).toBeNull();
    expect(useViewer.getState().images.nav1).toBeDefined();
  });

  it("surfaces a failed close instead of silently leaving the dataset selected", async () => {
    vi.mocked(listFourD).mockResolvedValue([fourdMeta()]);
    vi.mocked(fetchFourDMeanPattern).mockResolvedValue(raster(64, 64));
    vi.mocked(fetchFourDNav).mockResolvedValue(imageMeta("nav1"));
    vi.mocked(fetchData16).mockResolvedValue(raster(5, 4));
    vi.mocked(closeFourD).mockRejectedValue(new Error("unknown 4D dataset id: d1"));

    render(<FourDWorkshop />);
    fireEvent.change(await screen.findByLabelText("4D-STEM dataset"), {
      target: { value: "d1" },
    });
    await screen.findByText("mean pattern");

    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    await waitFor(() => expect(closeFourD).toHaveBeenCalledWith("d1"));
    // the failure is surfaced, not swallowed, and the selection is left
    // alone rather than clearing state for a close that never happened
    await screen.findByText(/close dataset: unknown 4D dataset id: d1/);
    expect(screen.getByText("mean pattern")).toBeVisible();
  });

  it("Show nav image ingests the nav ImageMeta into the main viewer store", async () => {
    vi.mocked(listFourD).mockResolvedValue([fourdMeta()]);
    vi.mocked(fetchFourDMeanPattern).mockResolvedValue(raster(64, 64));
    vi.mocked(fetchFourDNav).mockResolvedValue(imageMeta("nav1"));
    vi.mocked(fetchData16).mockResolvedValue(raster(5, 4));

    render(<FourDWorkshop />);
    fireEvent.change(await screen.findByLabelText("4D-STEM dataset"), {
      target: { value: "d1" },
    });
    await screen.findByText("mean pattern");

    fireEvent.click(screen.getByRole("button", { name: "Show nav image" }));

    await waitFor(() => expect(useViewer.getState().images.nav1).toBeDefined());
  });

  it("Probe on Stage shows the nav image, arms fourdnav, and a picked pixel drives the probe (#14 v2)", async () => {
    vi.mocked(listFourD).mockResolvedValue([fourdMeta()]);
    vi.mocked(fetchFourDMeanPattern).mockResolvedValue(raster(64, 64));
    vi.mocked(fetchFourDNav).mockResolvedValue(imageMeta("nav1"));
    vi.mocked(fetchData16).mockResolvedValue(raster(5, 4));
    vi.mocked(fetchFourDPattern).mockResolvedValue(raster(64, 64));

    render(<FourDWorkshop />);
    fireEvent.change(await screen.findByLabelText("4D-STEM dataset"), {
      target: { value: "d1" },
    });
    await screen.findByText("mean pattern");

    fireEvent.click(screen.getByRole("button", { name: "Probe on Stage" }));

    // showNavImage() ingests the nav image (making it the active Stage
    // image) BEFORE fourdnav is armed — useFourDNavProbeSync gates on that
    await waitFor(() => expect(useViewer.getState().images.nav1).toBeDefined());
    await waitFor(() => expect(useViewer.getState().captureMode).toBe("fourdnav"));
    expect(screen.getByRole("button", { name: "Stop probing" })).toBeVisible();

    // a pixel published on the main Stage (as Stage.tsx's pointer handlers
    // would via setFourdNavPixel) reaches this workshop's own probe state
    act(() => {
      useViewer.getState().setFourdNavPixel([8, 42]);
    });
    expect(useFourD.getState().probe).toEqual({ y: 7, x: 41 });

    fireEvent.click(screen.getByRole("button", { name: "Stop probing" }));
    expect(useViewer.getState().captureMode).toBe("none");
  });
});
