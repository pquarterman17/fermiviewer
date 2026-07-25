import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { edsElementMap } from "../../lib/api";
import { EDS_MAP_DEBOUNCE_MS, useEdsElementMap } from "./useEdsElementMap";

vi.mock("../../lib/api", () => ({ edsElementMap: vi.fn() }));

const response = {
  map: [[1]],
  shape: [1, 1] as [number, number],
  e_lo: 2,
  e_hi: 3,
  bg: "none",
  total_counts: 1,
  map_meta: null,
};

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe("useEdsElementMap", () => {
  it("coalesces rapid window changes into the final request", async () => {
    vi.useFakeTimers();
    vi.mocked(edsElementMap).mockResolvedValue(response);
    const { result } = renderHook(() =>
      useEdsElementMap({
        imageId: "cube",
        e0Kev: 30,
        isOpen: (id): id is string => id === "cube",
        onStatus: () => {},
      }),
    );

    act(() => {
      result.current.recomputeMap(1, 2, "linear");
      result.current.recomputeMap(2, 3, "none");
      result.current.recomputeMap(3, 4, "bremsstrahlung", 22);
    });
    expect(result.current.mapBusy).toBe(true);
    expect(edsElementMap).not.toHaveBeenCalled();
    await act(() => vi.advanceTimersByTimeAsync(EDS_MAP_DEBOUNCE_MS));
    expect(edsElementMap).toHaveBeenCalledOnce();
    expect(edsElementMap).toHaveBeenCalledWith(
      "cube",
      3,
      4,
      expect.objectContaining({
        bg: "bremsstrahlung",
        e0Kev: 22,
        signal: expect.any(AbortSignal),
      }),
    );
  });

  it("aborts an in-flight request when a newer map supersedes it", async () => {
    vi.useFakeTimers();
    vi.mocked(edsElementMap).mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() =>
      useEdsElementMap({
        imageId: "cube",
        e0Kev: 30,
        isOpen: (id): id is string => id === "cube",
        onStatus: () => {},
      }),
    );

    act(() => result.current.recomputeMap(1, 2, "linear"));
    await act(() => vi.advanceTimersByTimeAsync(EDS_MAP_DEBOUNCE_MS));
    const signal = vi.mocked(edsElementMap).mock.calls[0][3]?.signal;
    expect(signal?.aborted).toBe(false);
    act(() => result.current.recomputeMap(2, 3, "linear"));
    expect(signal?.aborted).toBe(true);
  });
});
