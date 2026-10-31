import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CalibrationResult, DetectResult, ImageMeta } from "../../lib/api";
import { useViewer } from "../../store/viewer";

vi.mock("../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/api")>();
  return {
    ...actual,
    listDiffractionPhases: vi.fn().mockResolvedValue([]),
    diffractionDetectWithRoi: vi.fn(),
    diffractionCalibrate: vi.fn(),
  };
});

import { diffractionCalibrate, diffractionDetectWithRoi } from "../../lib/api";
import DiffractionWorkshop from "./DiffractionWorkshop";

function patternMeta(id: string): ImageMeta {
  return {
    id,
    name: `${id}.dm4`,
    kind: "image",
    shape: [256, 256],
    dtype: "float32",
    pixel_size: null,
    pixel_unit: "",
    value_unit: "counts",
    n_channels: null,
    energy_first: null,
    energy_last: null,
    energy_units: "",
    stage_tilt_deg: null,
    meta: {},
  };
}

const calibration: CalibrationResult = {
  ellipse: {
    center_row: 128,
    center_col: 128,
    a: 61.2,
    b: 60.4,
    theta_deg: 12,
    eccentricity: 0.161,
    mean_radius: 60.8,
  },
  n_points: 240,
  rms_residual_px: 0.42,
  d_known_ang: 2.35,
  camera_constant_px_ang: null,
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => { resolve = next; });
  return { promise, resolve };
}

afterEach(() => {
  vi.clearAllMocks();
  useViewer.setState({ images: {}, order: [], activeId: null, selected: [] });
});

describe("DiffractionWorkshop stale responses", () => {
  it("drops spots detected on a pattern that is no longer active", async () => {
    const pending = deferred<DetectResult>();
    vi.mocked(diffractionDetectWithRoi).mockReturnValue(pending.promise);
    useViewer.getState().ingest([patternMeta("a"), patternMeta("b")]);
    useViewer.getState().setActive("a");
    render(<DiffractionWorkshop />);

    fireEvent.click(screen.getByRole("button", { name: "Detect" }));
    const signal = vi.mocked(diffractionDetectWithRoi).mock.calls[0]![1]!.signal!;
    act(() => useViewer.getState().setActive("b"));
    await act(async () => pending.resolve({ spots: [[10, 12], [40, 44], [90, 91]], n: 3 }));

    expect(signal.aborted).toBe(true);
    expect(screen.queryByText("3 spots")).toBeNull();
    expect(screen.getByRole("button", { name: "Detect" })).not.toBeDisabled();
    expect(screen.getByRole("button", { name: "Index" })).toBeDisabled();
  });

  it("drops a ring calibration that lands after the pattern changes", async () => {
    const pending = deferred<CalibrationResult>();
    vi.mocked(diffractionCalibrate).mockReturnValue(pending.promise);
    useViewer.getState().ingest([patternMeta("a"), patternMeta("b")]);
    useViewer.getState().setActive("a");
    render(<DiffractionWorkshop />);

    fireEvent.click(screen.getByRole("tab", { name: "Calibrate" }));
    fireEvent.change(screen.getByPlaceholderText("auto"), { target: { value: "2.35" } });
    fireEvent.click(screen.getByRole("button", { name: "Fit ellipse" }));
    act(() => useViewer.getState().setActive("b"));
    await act(async () => pending.resolve(calibration));

    expect(screen.queryByText(/ecc 0\.161/)).toBeNull();
    expect(screen.getByRole("button", { name: "Fit ellipse" })).not.toBeDisabled();
  });

  it("keeps the newest pattern's calibration when an older fit resolves late", async () => {
    const first = deferred<CalibrationResult>();
    vi.mocked(diffractionCalibrate)
      .mockReturnValueOnce(first.promise)
      .mockResolvedValueOnce({ ...calibration, ellipse: { ...calibration.ellipse, eccentricity: 0.222 } });
    useViewer.getState().ingest([patternMeta("a"), patternMeta("b")]);
    useViewer.getState().setActive("a");
    render(<DiffractionWorkshop />);

    fireEvent.click(screen.getByRole("tab", { name: "Calibrate" }));
    fireEvent.click(screen.getByRole("button", { name: "Fit ellipse" }));
    act(() => useViewer.getState().setActive("b"));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Fit ellipse" }));
    });
    expect(screen.getByText(/ecc 0\.222/)).toBeVisible();

    await act(async () => first.resolve(calibration));
    expect(screen.getByText(/ecc 0\.222/)).toBeVisible();
    expect(screen.queryByText(/ecc 0\.161/)).toBeNull();
    expect(screen.getByRole("button", { name: "Fit ellipse" })).not.toBeDisabled();
  });
});
