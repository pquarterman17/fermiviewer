import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
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

const reopenedPhase: ImageMeta = { ...phase, id: "phase-reopened" };
const amplitude: ImageMeta = {
  ...phase, id: "amplitude", name: "scan.spm · Amplitude", value_unit: "nm",
  meta: { ...root.meta, channel_label: "Amplitude" },
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
      expect(openAfmChannels).toHaveBeenCalledWith(
        "height", ["Phase (retrace)"], expect.objectContaining({ signal: expect.any(AbortSignal) }),
      );
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
      .mockResolvedValue([
        { label: "Height (retrace)", image_id: "height" },
        { label: "Phase (retrace)", image_id: "phase" },
      ]);
    vi.mocked(openAfmChannels).mockResolvedValue([phase]);
    render(<AfmChannelPicker meta={root} />);

    fireEvent.click(await screen.findByRole("button", { name: "Open remaining 1" }));
    await waitFor(() => expect(useViewer.getState().images.phase).toEqual(phase));
    expect(openAfmChannels).toHaveBeenCalledWith(
      "height", ["Phase (retrace)"], expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(useViewer.getState().activeId).toBe("height");
  });

  it("reopens a channel whose cached image id has since closed", async () => {
    vi.mocked(listAfmChannels).mockResolvedValue([
      { label: "Height (retrace)", image_id: "height" },
      { label: "Phase (retrace)", image_id: "phase" },
    ]);
    vi.mocked(openAfmChannels).mockResolvedValue([reopenedPhase]);
    useViewer.setState({
      order: [root.id, phase.id],
      images: { [root.id]: root, [phase.id]: phase },
    });
    render(<AfmChannelPicker meta={root} />);
    const selector = await screen.findByRole("combobox");

    act(() => {
      useViewer.setState({ order: [root.id], images: { [root.id]: root } });
    });
    await waitFor(() =>
      expect(screen.getByRole("option", { name: /Phase.*closed/ })).toBeVisible(),
    );
    fireEvent.change(selector, { target: { value: "Phase (retrace)" } });

    await waitFor(() => {
      expect(openAfmChannels).toHaveBeenCalledWith(
        "height", ["Phase (retrace)"], expect.objectContaining({ signal: expect.any(AbortSignal) }),
      );
      expect(useViewer.getState().activeId).toBe("phase-reopened");
    });
    expect(useViewer.getState().images["phase-reopened"]).toEqual(reopenedPhase);
  });

  it("keeps only the newest channel choice when responses finish out of order", async () => {
    let finishPhase!: (value: ImageMeta[]) => void;
    let finishAmplitude!: (value: ImageMeta[]) => void;
    vi.mocked(listAfmChannels).mockResolvedValue([
      { label: "Height (retrace)", image_id: "height" },
      { label: "Phase (retrace)", image_id: null },
      { label: "Amplitude", image_id: null },
    ]);
    vi.mocked(openAfmChannels)
      .mockImplementationOnce(() => new Promise((resolve) => { finishPhase = resolve; }))
      .mockImplementationOnce(() => new Promise((resolve) => { finishAmplitude = resolve; }));
    render(<AfmChannelPicker meta={root} />);

    const selector = await screen.findByRole("combobox");
    fireEvent.change(selector, { target: { value: "Phase (retrace)" } });
    fireEvent.change(selector, { target: { value: "Amplitude" } });
    await act(async () => finishAmplitude([amplitude]));
    await waitFor(() => expect(useViewer.getState().activeId).toBe("amplitude"));
    await act(async () => finishPhase([phase]));

    expect(useViewer.getState().activeId).toBe("amplitude");
    expect(useViewer.getState().images.phase).toBeUndefined();
    expect(screen.getByRole("status")).toHaveTextContent("Amplitude opened");
  });

  it("clears pending state when navigating to an already-open channel", async () => {
    vi.mocked(listAfmChannels).mockResolvedValue([
      { label: "Height (retrace)", image_id: "height" },
      { label: "Phase (retrace)", image_id: "phase" },
      { label: "Amplitude", image_id: null },
    ]);
    vi.mocked(openAfmChannels).mockImplementation(() => new Promise(() => undefined));
    useViewer.setState({
      order: [root.id, phase.id],
      images: { [root.id]: root, [phase.id]: phase },
    });
    render(<AfmChannelPicker meta={root} />);

    const selector = await screen.findByRole("combobox");
    fireEvent.change(selector, { target: { value: "Amplitude" } });
    expect(await screen.findByRole("status")).toHaveTextContent("Opening Amplitude");
    expect(screen.getByRole("button", { name: "Open remaining 1" })).toBeDisabled();

    fireEvent.change(selector, { target: { value: "Phase (retrace)" } });
    expect(useViewer.getState().activeId).toBe("phase");
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getByRole("button", { name: "Open remaining 1" })).toBeEnabled();
  });
});
