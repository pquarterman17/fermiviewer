import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../lib/api/regions", () => ({ previewRegion: vi.fn() }));

import type { ProjectRegion } from "../../lib/api";
import { previewRegion, type RegionPreviewResponse } from "../../lib/api/regions";
import { useRegionPreviewStore } from "../../store/regionPreview";
import RegionMaskPreview from "./RegionMaskPreview";

const region: ProjectRegion = { id: "r1", name: null, region_class: null, parts: [], meta: {} };
const summary: RegionPreviewResponse = {
  pixel_count: 196, image_pixels: 2400, fraction: 196 / 2400, rect: [6, 6, 15, 25],
  bbox_pixels: 200, exact_mask: true, area_calibrated: null, unit: "px",
  provenance: {}, mask_png: null,
};

describe("RegionMaskPreview", () => {
  afterEach(() => {
    vi.mocked(previewRegion).mockReset();
    act(() => useRegionPreviewStore.setState({ mask: null }));
  });

  it("summarizes the region and paints its raster on demand", async () => {
    vi.mocked(previewRegion).mockImplementation(async (req) => ({
      ...summary,
      mask_png: req.include_mask ? "AA==" : null,
    }));
    const { unmount } = render(<RegionMaskPreview imageId="img" setId="picked" region={region} />);
    await waitFor(() =>
      expect(screen.getByText(/196 px/).textContent).toContain("exact mask in a 200 px box"),
    );
    expect(useRegionPreviewStore.getState().mask).toBeNull();

    fireEvent.click(screen.getByRole("checkbox"));
    await waitFor(() =>
      expect(useRegionPreviewStore.getState().mask).toEqual({
        imageId: "img",
        regionRef: "picked/r1",
        rect: [6, 6, 15, 25],
        href: "data:image/png;base64,AA==",
      }),
    );
    expect(previewRegion).toHaveBeenLastCalledWith({
      image_id: "img", region_ref: "picked/r1", roi: "", include_mask: true,
    });

    // deselecting (unmount) takes the mask off the stage
    unmount();
    expect(useRegionPreviewStore.getState().mask).toBeNull();
  });

  it("cannot paint a plain rectangle, and says why", async () => {
    vi.mocked(previewRegion).mockResolvedValue({ ...summary, exact_mask: false });
    render(<RegionMaskPreview imageId="img" setId="picked" region={region} />);
    await waitFor(() =>
      expect((screen.getByRole("checkbox") as HTMLInputElement).disabled).toBe(true),
    );
    expect(screen.getByText(/outline is the mask/)).toBeTruthy();
  });
});
