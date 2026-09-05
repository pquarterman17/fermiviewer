import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../lib/api/regions", () => ({ previewRegion: vi.fn() }));

import { previewRegion } from "../../lib/api/regions";
import AnalysisRegionSelect from "./AnalysisRegionSelect";

const options = [
  { value: "whole", label: "Whole image" },
  { value: "selected", label: "Selected ROI" },
];

describe("AnalysisRegionSelect preview", () => {
  afterEach(() => {
    vi.mocked(previewRegion).mockReset();
  });

  it("reports what the choice selects, resolved by the server", async () => {
    vi.mocked(previewRegion).mockResolvedValue({
      pixel_count: 200, image_pixels: 4000, fraction: 0.05, rect: [3, 3, 12, 22],
      bbox_pixels: 200, exact_mask: false, area_calibrated: 50, unit: "nm",
      provenance: {}, mask_png: null,
    });
    render(
      <AnalysisRegionSelect
        choice="selected"
        options={options}
        disabled={false}
        onChange={() => {}}
        imageId="img"
        roi={[3, 3, 12, 22]}
      />,
    );
    await waitFor(() =>
      expect(screen.getByTestId("region-preview-summary").textContent).toBe(
        "200 px · 5.0 % of image · 50 nm²",
      ),
    );
    expect(previewRegion).toHaveBeenCalledWith({
      image_id: "img", region_ref: "", roi: "3,3,12,22", include_mask: false,
    });
  });

  it("stays a plain select without an image", () => {
    render(
      <AnalysisRegionSelect choice="whole" options={options} disabled={false} onChange={() => {}} />,
    );
    expect(screen.queryByTestId("region-preview-summary")).toBeNull();
    expect(previewRegion).not.toHaveBeenCalled();
  });

  it("shows the server's reason when a choice cannot be previewed", async () => {
    vi.mocked(previewRegion).mockRejectedValue(new Error("region selects no pixels"));
    render(
      <AnalysisRegionSelect
        choice="selected"
        options={options}
        disabled={false}
        onChange={() => {}}
        imageId="img"
        roi={[1, 1, 1, 1]}
      />,
    );
    await waitFor(() =>
      expect(screen.getByTestId("region-preview-summary").textContent).toBe(
        "preview: region selects no pixels",
      ),
    );
  });
});
