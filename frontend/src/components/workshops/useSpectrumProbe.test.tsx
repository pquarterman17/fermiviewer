import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchSpectrum, type Spectrum } from "../../lib/api";
import {
  SPECTRUM_PROBE_DEBOUNCE_MS,
  useSpectrumProbe,
} from "./useSpectrumProbe";

vi.mock("../../lib/api", () => ({ fetchSpectrum: vi.fn() }));

const spectrum: Spectrum = { energy: [0, 1], counts: [4, 8], units: "eV" };

beforeEach(() => {
  vi.useFakeTimers();
  vi.mocked(fetchSpectrum).mockReset().mockResolvedValue(spectrum);
});

afterEach(() => vi.useRealTimers());

describe("useSpectrumProbe", () => {
  it("coalesces rapid pixels into one request for the latest pixel", async () => {
    const onSpectrum = vi.fn();
    const onError = vi.fn();
    const { rerender } = renderHook(
      ({ pixel }: { pixel: [number, number] }) =>
        useSpectrumProbe({
          imageId: "cube",
          pixel,
          enabled: true,
          onSpectrum,
          onError,
        }),
      { initialProps: { pixel: [1, 2] as [number, number] } },
    );

    rerender({ pixel: [3, 4] });
    rerender({ pixel: [5, 6] });
    await act(() => vi.advanceTimersByTimeAsync(SPECTRUM_PROBE_DEBOUNCE_MS));

    expect(fetchSpectrum).toHaveBeenCalledOnce();
    expect(fetchSpectrum).toHaveBeenCalledWith(
      "cube",
      [5, 6, 5, 6],
      { signal: expect.any(AbortSignal) },
    );
    expect(onSpectrum).toHaveBeenCalledWith(spectrum, [5, 6, 5, 6]);
    expect(onError).not.toHaveBeenCalled();
  });

  it("aborts an in-flight request when a newer pixel arrives", async () => {
    vi.mocked(fetchSpectrum).mockImplementation(() => new Promise(() => {}));
    const { rerender } = renderHook(
      ({ pixel }: { pixel: [number, number] }) =>
        useSpectrumProbe({
          imageId: "cube",
          pixel,
          enabled: true,
          onSpectrum: vi.fn(),
          onError: vi.fn(),
        }),
      { initialProps: { pixel: [1, 2] as [number, number] } },
    );
    await act(() => vi.advanceTimersByTimeAsync(SPECTRUM_PROBE_DEBOUNCE_MS));
    const firstSignal = vi.mocked(fetchSpectrum).mock.calls[0][2]?.signal;

    rerender({ pixel: [7, 9] });
    expect(firstSignal?.aborted).toBe(true);
    await act(() => vi.advanceTimersByTimeAsync(SPECTRUM_PROBE_DEBOUNCE_MS));
    expect(fetchSpectrum).toHaveBeenCalledTimes(2);
  });

  it("cancels a pending debounce when disabled", async () => {
    const { rerender } = renderHook(
      ({ enabled }) =>
        useSpectrumProbe({
          imageId: "cube",
          pixel: [2, 3],
          enabled,
          onSpectrum: vi.fn(),
          onError: vi.fn(),
        }),
      { initialProps: { enabled: true } },
    );
    rerender({ enabled: false });
    await act(() => vi.advanceTimersByTimeAsync(SPECTRUM_PROBE_DEBOUNCE_MS));
    expect(fetchSpectrum).not.toHaveBeenCalled();
  });
});
