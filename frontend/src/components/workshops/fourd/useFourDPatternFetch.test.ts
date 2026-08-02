import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../lib/api", () => ({ fetchFourDPattern: vi.fn() }));

import { fetchFourDPattern, type Raster16 } from "../../../lib/api";
import { useFourD } from "../../../store/fourd";
import { FOURD_PATTERN_DEBOUNCE_MS, useFourDPatternFetch } from "./useFourDPatternFetch";

function raster(): Raster16 {
  return { data: new Uint16Array([1, 2, 3, 4]), w: 2, h: 2, vmin: 0, vmax: 10, nFrames: null };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.mocked(fetchFourDPattern).mockReset().mockResolvedValue(raster());
  useFourD.setState({
    probe: null,
    patternRaster: null,
    busyPattern: false,
    status: null,
  });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useFourDPatternFetch", () => {
  it("debounces a probe move into one pattern fetch and stores the raster", async () => {
    renderHook(() => useFourDPatternFetch("ds1"));

    act(() => {
      useFourD.getState().setProbe({ y: 1, x: 2 });
    });
    await act(() => vi.advanceTimersByTimeAsync(FOURD_PATTERN_DEBOUNCE_MS));

    expect(fetchFourDPattern).toHaveBeenCalledOnce();
    expect(fetchFourDPattern).toHaveBeenCalledWith(
      "ds1",
      1,
      2,
      { signal: expect.any(AbortSignal) },
    );
    expect(useFourD.getState().patternRaster).toEqual(raster());
    expect(useFourD.getState().busyPattern).toBe(false);
  });

  it("does nothing while no dataset is selected", async () => {
    renderHook(() => useFourDPatternFetch(null));
    act(() => {
      useFourD.getState().setProbe({ y: 0, x: 0 });
    });
    await act(() => vi.advanceTimersByTimeAsync(FOURD_PATTERN_DEBOUNCE_MS));
    expect(fetchFourDPattern).not.toHaveBeenCalled();
  });

  it("aborts an in-flight fetch when a newer probe arrives", async () => {
    vi.mocked(fetchFourDPattern).mockImplementation(() => new Promise(() => {}));
    renderHook(() => useFourDPatternFetch("ds1"));

    act(() => {
      useFourD.getState().setProbe({ y: 1, x: 1 });
    });
    await act(() => vi.advanceTimersByTimeAsync(FOURD_PATTERN_DEBOUNCE_MS));
    const firstSignal = vi.mocked(fetchFourDPattern).mock.calls[0][3]?.signal;

    act(() => {
      useFourD.getState().setProbe({ y: 2, x: 2 });
    });
    expect(firstSignal?.aborted).toBe(true);

    await act(() => vi.advanceTimersByTimeAsync(FOURD_PATTERN_DEBOUNCE_MS));
    expect(fetchFourDPattern).toHaveBeenCalledTimes(2);
  });

  it("reports a fetch failure through setStatus without crashing", async () => {
    vi.mocked(fetchFourDPattern).mockRejectedValue(new Error("boom"));
    renderHook(() => useFourDPatternFetch("ds1"));

    act(() => {
      useFourD.getState().setProbe({ y: 3, x: 3 });
    });
    await act(() => vi.advanceTimersByTimeAsync(FOURD_PATTERN_DEBOUNCE_MS));

    expect(useFourD.getState().status).toBe("pattern: boom");
    expect(useFourD.getState().busyPattern).toBe(false);
  });
});
