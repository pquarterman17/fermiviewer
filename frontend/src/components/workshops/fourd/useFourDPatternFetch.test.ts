import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../../lib/api")>();
  return { ...actual, fetchFourDPattern: vi.fn(), listFourD: vi.fn() };
});

import {
  fetchFourDPattern,
  FourDNotFoundError,
  listFourD,
  type Raster16,
} from "../../../lib/api";
import { useFourD } from "../../../store/fourd";
import { FOURD_PATTERN_DEBOUNCE_MS, useFourDPatternFetch } from "./useFourDPatternFetch";

function raster(): Raster16 {
  return { data: new Uint16Array([1, 2, 3, 4]), w: 2, h: 2, vmin: 0, vmax: 10, nFrames: null };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.mocked(fetchFourDPattern).mockReset().mockResolvedValue(raster());
  vi.mocked(listFourD).mockReset().mockResolvedValue([]);
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

  it("a stale/closed dataset (404) refreshes the list instead of leaving an error note", async () => {
    vi.mocked(fetchFourDPattern).mockRejectedValue(new FourDNotFoundError("unknown 4D dataset id: ds1"));
    renderHook(() => useFourDPatternFetch("ds1"));

    act(() => {
      useFourD.getState().setProbe({ y: 5, x: 5 });
    });
    await act(() => vi.advanceTimersByTimeAsync(FOURD_PATTERN_DEBOUNCE_MS));

    expect(listFourD).toHaveBeenCalledOnce();
    // not the raw error message — that's exactly the "red error toast loop"
    // this branch exists to avoid
    expect(useFourD.getState().status).not.toBe("pattern: unknown 4D dataset id: ds1");
  });

  it("an older probe's response resolving AFTER a newer one's does not clobber the newer result", async () => {
    // classic race: two debounced requests are both allowed to actually
    // settle (mock fetch doesn't honor AbortSignal, matching a browser fetch
    // that started before the abort landed) — the AbortController's own
    // "aborted" flag must still be what protects the final state, since
    // nothing else does.
    let resolveFirst: (r: ReturnType<typeof raster>) => void = () => {};
    let resolveSecond: (r: ReturnType<typeof raster>) => void = () => {};
    vi.mocked(fetchFourDPattern)
      .mockImplementationOnce(() => new Promise((r) => { resolveFirst = r; }))
      .mockImplementationOnce(() => new Promise((r) => { resolveSecond = r; }));
    renderHook(() => useFourDPatternFetch("ds1"));

    act(() => useFourD.getState().setProbe({ y: 1, x: 1 }));
    await act(() => vi.advanceTimersByTimeAsync(FOURD_PATTERN_DEBOUNCE_MS));
    act(() => useFourD.getState().setProbe({ y: 2, x: 2 }));
    await act(() => vi.advanceTimersByTimeAsync(FOURD_PATTERN_DEBOUNCE_MS));
    expect(fetchFourDPattern).toHaveBeenCalledTimes(2);

    const second = { data: new Uint16Array([9, 9, 9, 9]), w: 2, h: 2, vmin: 0, vmax: 10, nFrames: null };
    // resolve the NEWER request first, then the stale/aborted older one late
    await act(async () => resolveSecond(second));
    await act(async () => resolveFirst(raster()));

    expect(useFourD.getState().patternRaster).toEqual(second);
  });

  it("cancels the in-flight fetch on unmount instead of setting state afterwards", async () => {
    let resolvePattern: (r: ReturnType<typeof raster>) => void = () => {};
    vi.mocked(fetchFourDPattern).mockImplementation(
      () => new Promise((r) => { resolvePattern = r; }),
    );
    const { unmount } = renderHook(() => useFourDPatternFetch("ds1"));

    act(() => useFourD.getState().setProbe({ y: 4, x: 4 }));
    await act(() => vi.advanceTimersByTimeAsync(FOURD_PATTERN_DEBOUNCE_MS));
    expect(useFourD.getState().busyPattern).toBe(true);

    unmount();
    // the request resolves after the component (and hook) are gone
    await act(async () => resolvePattern(raster()));

    // unmount aborted the request, so its resolution must not be applied —
    // busyPattern is left as-is rather than a post-unmount write racing in
    expect(useFourD.getState().patternRaster).toBeNull();
  });
});
