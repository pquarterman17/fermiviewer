import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  listAfmChannels,
  openAfmChannels,
  type ImageMeta,
} from "../../lib/api";
import { useViewer } from "../../store/viewer";
import AfmChannelPicker from "./AfmChannelPicker";

vi.mock("../../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../lib/api")>()),
  listAfmChannels: vi.fn(),
  openAfmChannels: vi.fn(),
}));

const root: ImageMeta = {
  id: "height",
  name: "scan.spm",
  kind: "image",
  shape: [10, 10],
  dtype: "float32",
  pixel_size: 1,
  pixel_unit: "nm",
  value_unit: "nm",
  n_channels: null,
  energy_first: null,
  energy_last: null,
  energy_units: "",
  stage_tilt_deg: null,
  meta: {
    parser: "nanoscope",
    channel_label: "Height (retrace)",
  },
};

const phase: ImageMeta = {
  ...root,
  id: "phase",
  name: "scan.spm · Phase (retrace)",
  value_unit: "deg",
  meta: { ...root.meta, channel_label: "Phase (retrace)" },
};

beforeEach(() => {
  vi.mocked(listAfmChannels).mockReset();
  vi.mocked(openAfmChannels).mockReset();
  useViewer.setState({
    order: [root.id],
    activeId: root.id,
    images: { [root.id]: root },
    selected: [root.id],
    status: "ready",
  });
});

describe("AFM channel picker", () => {
  it("stays absent for a single-channel scan", async () => {
    vi.mocked(listAfmChannels).mockResolvedValue([
      { label: "Height (retrace)", image_id: "height" },
    ]);
    render(<AfmChannelPicker meta={root} />);
    await waitFor(() => expect(listAfmChannels).toHaveBeenCalled());
    expect(screen.queryByRole("region", { name: "AFM scan channels" })).toBeNull();
  });

  it("opens only the selected closed channel and navigates to it", async () => {
    vi.mocked(listAfmChannels).mockResolvedValue([
      { label: "Height (retrace)", image_id: "height" },
      { label: "Phase (retrace)", image_id: null },
    ]);
    vi.mocked(openAfmChannels).mockResolvedValue([phase]);
    render(<AfmChannelPicker meta={root} />);

    const selector = await screen.findByRole("combobox");
    fireEvent.change(selector, { target: { value: "Phase (retrace)" } });

    await waitFor(() => {
      expect(openAfmChannels).toHaveBeenCalledWith("height", ["Phase (retrace)"]);
      expect(useViewer.getState().activeId).toBe("phase");
    });
    expect(useViewer.getState().images.phase).toEqual(phase);
  });

  it("opens all remaining channels without changing the active image", async () => {
    vi.mocked(listAfmChannels)
      .mockResolvedValueOnce([
        { label: "Height (retrace)", image_id: "height" },
        { label: "Phase (retrace)", image_id: null },
      ])
      .mockResolvedValueOnce([
        { label: "Height (retrace)", image_id: "height" },
        { label: "Phase (retrace)", image_id: "phase" },
      ]);
    vi.mocked(openAfmChannels).mockResolvedValue([phase]);
    render(<AfmChannelPicker meta={root} />);

    fireEvent.click(await screen.findByRole("button", { name: "Open remaining 1" }));
    await waitFor(() => expect(useViewer.getState().images.phase).toEqual(phase));
    expect(openAfmChannels).toHaveBeenCalledWith("height");
    expect(useViewer.getState().activeId).toBe("height");
  });
});
