import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ImageMeta } from "../../lib/api";
import { useViewer } from "../../store/viewer";

vi.mock("../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/api")>();
  return { ...actual, eelsSvd: vi.fn() };
});

import { eelsSvd } from "../../lib/api";
import EelsAdvanced from "./EelsAdvanced";

function meta(id: string, kind: ImageMeta["kind"]): ImageMeta {
  return {
    id, name: id, kind, shape: kind === "image" ? [4, 4] : [4, 4, 16],
    dtype: "float32", pixel_size: null, pixel_unit: "px", value_unit: "",
    n_channels: kind === "image" ? null : 16, energy_first: 0, energy_last: 15,
    energy_units: "eV", stage_tilt_deg: null, meta: {},
  } as ImageMeta;
}

afterEach(() => {
  useViewer.setState({ images: {}, order: [], activeId: null, selected: [] });
});

describe("EelsAdvanced SVD", () => {
  it("keeps the source cube active so the result stays on screen", async () => {
    useViewer.getState().ingest([meta("cube", "spectrum_image")]);
    useViewer.getState().setActive("cube");
    vi.mocked(eelsSvd).mockResolvedValue({
      explained: [61.5, 20.25],
      score_maps: [meta("pc1", "image"), meta("pc2", "image")],
    } as unknown as Awaited<ReturnType<typeof eelsSvd>>);

    render(<EelsAdvanced activeId="cube" isCube units="eV" tabbed visible />);
    fireEvent.click(screen.getByRole("button", { name: "SVD" }));

    await waitFor(() => expect(screen.getByText(/PC1 61\.5%/)).toBeVisible());
    // the score maps are in the library, but the cube is still the subject
    expect(useViewer.getState().order).toEqual(["cube", "pc1", "pc2"]);
    expect(useViewer.getState().activeId).toBe("cube");
  });

  it("drops an SVD that lands after the cube changes", async () => {
    useViewer.getState().ingest([
      meta("cube", "spectrum_image"),
      meta("other", "spectrum_image"),
    ]);
    useViewer.getState().setActive("cube");
    let resolve!: (value: Awaited<ReturnType<typeof eelsSvd>>) => void;
    vi.mocked(eelsSvd).mockReturnValue(new Promise((next) => { resolve = next; }));

    const view = render(<EelsAdvanced activeId="cube" isCube units="eV" tabbed visible />);
    fireEvent.click(screen.getByRole("button", { name: "SVD" }));
    act(() => useViewer.getState().setActive("other"));
    view.rerender(<EelsAdvanced activeId="other" isCube units="eV" tabbed visible />);
    await act(async () => resolve({
      explained: [61.5, 20.25],
      score_maps: [meta("pc1", "image"), meta("pc2", "image")],
    } as unknown as Awaited<ReturnType<typeof eelsSvd>>));

    expect(screen.queryByText(/PC1 61\.5%/)).toBeNull();
    expect(useViewer.getState().order).toEqual(["cube", "other"]);
    expect(useViewer.getState().activeId).toBe("other");
    expect(screen.getByRole("button", { name: "SVD" })).not.toBeDisabled();
  });
});
